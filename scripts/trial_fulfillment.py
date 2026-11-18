#!/usr/bin/env python
"""Reproduce a bounded requirement-change trial without editing the baseline.

    uv run python scripts/trial_fulfillment.py --output /tmp/fulfillment-trial

All selections reuse one prepared Spec per model revision. Full CLI reports,
inspection output and traces are saved under --output; summary.json is portable.
Times include validation, not imports, and are observations, not performance gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import prepare_model, validate_spec
from analint.validator.exploration_service import trace_query

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "examples/fulfillment"
CHANGE = ROOT / "benchmarks/fulfillment_cancellation.py"
FAULT = ROOT / "benchmarks/fulfillment_missing_refund.py"
BUDGET = 20_000
SELECTIONS = {
    "full": None,
    "flows": ["flow:cancel_in_transit", "flow:deliver_normally"],
    "cancel_flow": ["flow:cancel_in_transit"],
    "delivery_flow": ["flow:deliver_normally"],
    "safety": ["query:no_money_for_nothing"],
    "availability": ["query:in_transit_refund_exists"],
    "recovery": ["query:settlement_always_reachable"],
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def stable(value: object) -> object:
    """Only per-check timing is excluded from report parity."""
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items() if key != "elapsed_ms"}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def cli(*args: str) -> tuple[int, dict]:
    process = subprocess.run(
        [sys.executable, "-c", "from analint.cli import app; app()", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    require(process.returncode in (0, 1, 4), f"CLI failed: {process.stderr}")
    return process.returncode, json.loads(process.stdout)


def run_trial(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    _, overview = cli("show", "-p", str(MODEL))
    _, impact = cli("affects", "Order.status", "-p", str(MODEL))
    save(output / "overview.json", overview)
    save(output / "impact.json", impact)
    _, query_details = cli("show", "query", "no_money_for_nothing", "-p", str(MODEL))
    save(output / "safety-query.json", query_details)
    base_actions = overview["actions"]
    source = CHANGE.read_text()
    start = source.index("# BEGIN NEW ACTION:")
    end = source.index("# END NEW ACTION") + len("# END NEW ACTION")
    before = (
        source[:start]
        + "from fulfillment.actions import cancel_by_customer as cancel_after_dispatch\n"
        + source[end:]
    )
    records = []
    with tempfile.TemporaryDirectory(prefix="analint-fulfillment-") as temporary:
        temp = Path(temporary)
        patches = {"baseline": None}
        for name, content in (
            ("old_with_probe", before),
            ("changed", source),
            ("negative_control", source + "\n" + FAULT.read_text()),
        ):
            patch = temp / f"{name}.py"
            patch.write_text(content)
            patches[name] = patch
            # Keep the exact runnable hypothesis, including the old-rule probe.
            (output / f"{name}.py").write_text(content)

        for stage, patch in patches.items():
            prepared = prepare_model(MODEL, what_if=patch)
            require(not prepared.load_errors, f"{stage}: {prepared.load_errors}")
            require(not prepared.has_structural_errors, f"{stage}: structural error")
            spec = prepared.spec
            require(spec is not None, f"{stage}: missing model")
            members = {
                key: (getattr(spec, key), tuple(id(obj) for obj in getattr(spec, key)))
                for key in ("actions", "queries", "flows", "invariants", "scenarios")
            }
            declaration = repr(spec)
            actions = [action.id for action in spec.actions]
            require(set(base_actions) <= set(actions), f"{stage}: dropped baseline action")
            expected_actions = set(base_actions)
            if stage in ("changed", "negative_control"):
                expected_actions.add("cancel_after_dispatch")
            if stage == "negative_control":
                expected_actions.add("cancel_without_refund")
            require(set(actions) == expected_actions, f"{stage}: unexpected action membership")
            modes = {"full": None} if stage == "baseline" else SELECTIONS
            stage_reports = {}
            for sliced in (True, False):
                for mode, checks in modes.items():
                    started = perf_counter()
                    result = validate_spec(spec, checks=checks, sliced=sliced, max_states=BUDGET)
                    elapsed_ms = round((perf_counter() - started) * 1000, 3)
                    report = result_to_dict(result)
                    compact = result_to_dict(result, compact=True)
                    label = f"{stage}-{'sliced' if sliced else 'whole'}-{mode}"
                    save(output / f"{label}.json", report)
                    save(output / f"{label}-compact.json", compact)
                    require(not report["load_errors"], f"{label}: load error")
                    require(
                        all(
                            stage == "negative_control"
                            and f["code"] == "structural.no_scenarios"
                            and f["location"] == "action:cancel_without_refund"
                            for f in report["structural"]
                        ),
                        f"{label}: unexpected structural finding",
                    )
                    expected = "PASS"
                    if stage == "old_with_probe" and mode in (
                        "full",
                        "flows",
                        "cancel_flow",
                        "availability",
                    ):
                        expected = "FAIL"
                    if stage == "negative_control" and mode in ("full", "safety", "recovery"):
                        expected = "FAIL"
                    require(
                        report["verdict"] == expected, f"{label}: {report['verdict']} != {expected}"
                    )
                    require(compact["verdict"] == expected, f"{label}: compact verdict")
                    require(
                        all(q["status"] in ("PASS", "FAIL") for q in report["queries"]),
                        f"{label}: incomplete query",
                    )
                    if checks:
                        require(
                            report["selection"]["model_actions"] == actions, f"{label}: action loss"
                        )
                    stage_reports[sliced, mode] = report
                    records.append(
                        {
                            "stage": stage,
                            "sliced": sliced,
                            "selection": mode,
                            "verdict": report["verdict"],
                            "validation_ms": elapsed_ms,
                            "model_actions": len(actions),
                            "supporting": report.get("selection", {}).get("supporting", []),
                            "action_coverage": report.get("selection", {}).get("action_coverage"),
                            "model_coverage": report.get("model_coverage"),
                            "queries": [
                                {
                                    key: q[key]
                                    for key in ("id", "status", "states_explored", "trace")
                                }
                                for q in report["queries"]
                            ],
                            "flows": [
                                {key: f[key] for key in ("id", "passed", "actions_run")}
                                for f in report["flows"]
                            ],
                            "full_bytes": len(json.dumps(report).encode()),
                            "compact_bytes": len(json.dumps(compact).encode()),
                        }
                    )
                full = stage_reports[sliced, "full"]
                expected_failures = {
                    "old_with_probe": {"in_transit_refund_exists"},
                    "negative_control": {"no_money_for_nothing", "settlement_always_reachable"},
                }.get(stage, set())
                require(
                    {q["id"] for q in full["queries"] if q["status"] == "FAIL"}
                    == expected_failures,
                    f"{stage}: unexpected failing properties",
                )
                require(
                    {s["id"] for s in full["scenarios"] if not s["passed"]}
                    == ({"cancel_dispatched"} if stage == "old_with_probe" else set()),
                    f"{stage}: unexpected scenario result",
                )
                require(
                    {f["id"] for f in full["flows"] if not f["passed"]}
                    == ({"cancel_in_transit"} if stage == "old_with_probe" else set()),
                    f"{stage}: unexpected flow result",
                )
                require(
                    all(i["status"] == "PASS" for i in full["invariants"]),
                    f"{stage}: invariant failure",
                )
                if stage != "baseline":
                    for mode in ("safety", "availability", "recovery"):
                        selected = stage_reports[sliced, mode]["queries"][0]
                        original = next(q for q in full["queries"] if q["id"] == selected["id"])
                        require(
                            selected["status"] == original["status"], f"{stage}/{mode}: full parity"
                        )
                    for flow_mode in ("flows", "cancel_flow", "delivery_flow"):
                        expected_flows = [
                            f for f in full["flows"] if f"flow:{f['id']}" in SELECTIONS[flow_mode]
                        ]
                        require(
                            stage_reports[sliced, flow_mode]["flows"] == expected_flows,
                            f"{stage}: {flow_mode} parity",
                        )
                require(repr(spec) == declaration, f"{stage}: declarations mutated")
                require(
                    all(
                        getattr(spec, key) is seq and tuple(map(id, seq)) == ids
                        for key, (seq, ids) in members.items()
                    ),
                    f"{stage}: model membership mutated",
                )
            for mode in modes:
                sliced_report, whole_report = stage_reports[True, mode], stage_reports[False, mode]
                require(
                    sliced_report["verdict"] == whole_report["verdict"],
                    f"{stage}/{mode}: slice parity",
                )
                require(
                    [(q["id"], q["status"]) for q in sliced_report["queries"]]
                    == [(q["id"], q["status"]) for q in whole_report["queries"]],
                    f"{stage}/{mode}: query parity",
                )
            # CLI and the reused in-memory Spec must agree, including selection metadata.
            args = ["check", str(MODEL), "-f", "json", "--max-states", str(BUDGET)]
            if patch:
                args += ["--what-if", str(patch), "--check", "query:no_money_for_nothing"]
            exit_code, cli_report = cli(*args)
            memory_report = stage_reports[True, "safety" if patch else "full"]
            require(stable(cli_report) == stable(memory_report), f"{stage}: CLI/library parity")
            require(
                exit_code == (1 if memory_report["verdict"] == "FAIL" else 0),
                f"{stage}: exit status",
            )
            save(output / f"{stage}-cli.json", {"exit_code": exit_code, "report": cli_report})

            if stage in ("changed", "negative_control"):
                # A new cache directory prevents a previous trial masquerading as a cold run.
                old_cache = os.environ.get("ANALINT_CACHE_DIR")
                os.environ["ANALINT_CACHE_DIR"] = str(temp / f"cache-{stage}")
                try:
                    for temperature in ("cold", "warm"):
                        cached = result_to_dict(
                            validate_spec(
                                spec, checks=SELECTIONS["safety"], max_states=BUDGET, cache=True
                            )
                        )
                        require(
                            list((temp / f"cache-{stage}").glob("*.json.z")),
                            f"{stage}: no cache entries written",
                        )
                        # The requested cache option is the only intentional metadata difference.
                        cached["selection"]["options"]["cache"] = False
                        require(
                            stable(cached) == stable(stage_reports[True, "safety"]),
                            f"{stage}: {temperature} cache parity",
                        )
                finally:
                    if old_cache is None:
                        os.environ.pop("ANALINT_CACHE_DIR", None)
                    else:
                        os.environ["ANALINT_CACHE_DIR"] = old_cache
                query_id = (
                    "in_transit_refund_exists" if stage == "changed" else "no_money_for_nothing"
                )
                trace = trace_query(MODEL, query_id, what_if=patch, max_states=BUDGET)
                save(output / f"{stage}-trace.json", trace)
                witness = stage_reports[True, "availability" if stage == "changed" else "safety"][
                    "queries"
                ][0]["trace"]
                expected_action = (
                    "cancel_after_dispatch" if stage == "changed" else "cancel_without_refund"
                )
                require(witness[-1] == expected_action, f"{stage}: wrong witness {witness}")
                require(
                    [step["action"] for step in trace["steps"]] == witness,
                    f"{stage}: trace/check mismatch",
                )
                require(
                    trace["final_state"]["Order.status"] == "OrderStatus.CANCELLED",
                    f"{stage}: wrong final order",
                )
                expected_payment = (
                    "PaymentStatus.REFUNDED" if stage == "changed" else "PaymentStatus.CAPTURED"
                )
                require(
                    trace["final_state"]["Payment.status"] == expected_payment,
                    f"{stage}: wrong final payment",
                )

        # What-if preparation must not leak actions/checks into the unchanged example.
        baseline_again = prepare_model(MODEL).spec
        require(
            [a.id for a in baseline_again.actions] == base_actions,
            "hypothesis leaked into baseline",
        )
        require(not baseline_again.flows, "hypothesis flows leaked into baseline")

    sources = [*sorted(MODEL.glob("*.py")), CHANGE, FAULT, Path(__file__).resolve()]
    source_hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
    }
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False
    ).stdout.strip()
    summary = {
        "schema": "analint.fulfillment-trial/v1",
        "checkout_revision": revision or None,
        "analint_version": version("analint"),
        "engine_sha256": hashlib.sha256(
            b"".join(p.read_bytes() for p in sorted((ROOT / "src/analint").rglob("*.py")))
        ).hexdigest(),
        "source_hashes": source_hashes,
        "python": platform.python_version(),
        "max_states": BUDGET,
        "timing_scope": "one validation per case, preparation excluded; not a benchmark or speedup claim",
        "scope": "repository example; external real-spec trial remains pending",
        "records": records,
    }
    save(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = run_trial(args.output)
    print(f"PASS: {len(summary['records'])} cases; reports in {args.output}")


if __name__ == "__main__":
    main()

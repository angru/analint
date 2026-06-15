# Evidence: GitHub branch-protection policy as an analint model

Дата: 15 июня 2026 (ревизия после ревью `reviews/4465e16-branch-protection-evidence.md`).

Первый внешний change-oriented кейс из ROADMAP evidence-gate (research/20).
Модель: `examples/branch_protection/` — GitHub protected-branch / required
pull-request policy. Реальная система, не придуманная под analint.

## Что верифицировано

Один bounded `PullRequest` (state-lifecycle OPEN→MERGED/CLOSED, approvals 0..2,
code_owner_approved, changes_requested, checks PENDING/PASSING/FAILING,
behind_base) + действия review/CI/base/merge/close. Политика merge — один
именованный предикат `mergeable`. **121 reachable state.**

Ценность — не «нашли баг» (политика корректна), а **доказанная
небайпасабельность по всем порядкам действий**:

- `merge_is_achievable` (Reachable) — happy-path существует; witness:
  `approve → checks_pass → code_owner_approve → merge` (два review, один из них —
  code owner).
- `never_merge_underapproved/without_code_owner/failing/with_changes/behind`
  (Unreachable) — merge никогда не обходит ни один пункт политики, при любом
  чередовании push (сбрасывает stale approvals), base_advanced, update_branch,
  checks и т.д. **Каждый `never_merge_*` — это и есть mutation-детектор своего
  правила**: убери конъюнкт из `mergeable` — соответствующий запрос станет FAIL.
- `merged_satisfied_policy` (Invariant, авто-проверка по reachable states) —
  каждое merged-состояние удовлетворяет политике.
- `code_owner_is_an_approval` (Invariant) — soundness абстракции: флаг
  code-owner не может стоять без хотя бы одного approval за ним.

Это то, что нельзя получить сценариями: сценарии проверяют «придуманные» пути,
queries — все 121.

## Source / assumption matrix

Трассируемость «реальная система → абстракция». Источник:
GitHub Docs, *About protected branches* /
*About protected branches → Require pull request reviews*
(<https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches>).

| GitHub rule | modeled field / action | assumption / omission | property |
|---|---|---|---|
| Require N approving reviews | `approvals: 0..2`, `approve` | N=2; threshold-capped (`saturate=True`), reviewers без идентичности | `never_merge_underapproved` |
| Require review from Code Owners | `code_owner_approved`, `code_owner_approve` | code-owner review **считается** одним approval (counts toward total) | `never_merge_without_code_owner`, `code_owner_is_an_approval` |
| Dismiss stale approvals on new commit | `push_commit`, `update_branch` сбрасывают `approvals`+`code_owner_approved` | «новый коммит» = push **или** update-from-base (merge base в head) | `flow_push_forces_reapproval` |
| «Changes requested» блокирует merge | `changes_requested`, `request_changes`, `dismiss_changes_request` | push **не** снимает blocking review — только явный dismiss/re-review | `never_merge_with_changes`, `flow_changes_request_blocks_until_dismissed` |
| Require status checks to pass | `checks: pending/passing/failing`, `checks_pass/fail` | один агрегированный статус, не набор отдельных checks | `never_merge_failing` |
| Require branches up to date (strict) | `behind_base`, `base_advanced`, `update_branch` | base двигается → PR behind; head не меняется, approvals целы | `never_merge_behind` |
| Merge только при выполнении политики | `merge` (pre=`mergeable`) | terminal MERGED/CLOSED заморожены | `merged_satisfied_policy`, `policy_always_holds` |
| Allow bypass / admin override | — | **намеренно опущено** (bypass disabled) | — |

Намеренные упрощения / что модель НЕ покрывает: несколько PR и merge queue;
идентичности ревьюверов («последний push одобрен кем-то другим»); привязка CI к
конкретному head SHA; admin bypass; асинхронная доставка/ретраи.

### Граница выразительности (честно)

«Changes requested addressed» и «stale review dismissed» — это **path/history**
свойства («ранее запросили изменения; были ли они сняты явно?»). У analint есть
только reachability над состоянием, не темпоральные свойства. Поэтому
`never_merge_with_changes` строго говоря доказывает лишь, что в момент merge флаг
снят — **не** что запрошенные изменения были адресованы. Гарантия здесь
структурная: `dismiss_changes_request` — единственный, кто снимает флаг, а push
его не трогает; `flow_changes_request_blocks_until_dismissed` — исполняемый
свидетель обязательного явного dismiss. Это ровно тот случай, где Quint/FizzBee с
их темпоральными свойствами строго сильнее — и это надо проверить портом.

## Change series (four requirement changes, each measured)

The evidence gate asks for a *series* of requirement changes with the diff and
cost of each, not a single edit. Each change below is a real GitHub branch-
protection setting, applied to the baseline model, measured with `analint check`,
then reverted — the committed model keeps the baseline configuration; what matters
is the saved diff and the measured blast radius. Baseline: **121 reachable
states**, 18 scenarios / 7 queries / 2 invariants / 2 flows, all green; the merge
witness is `approve → checks_pass → code_owner_approve → merge`.

| # | Requirement change (GitHub setting) | Edit cost | States | Blast radius | Profile |
|---|---|---|---|---|---|
| 1 | dismiss-stale-on-push **off** | −5 lines, 2 actions | 121 (same) | 2 scenarios + 1 flow FAIL; all 7 queries + 2 invariants stay green | local; reachability can't see "stale" |
| 2 | strict → **loose** checks | 1 line (drop a conjunct) | 121 → 122 | `never_merge_behind` + `sc_merge_behind_base` FAIL; policy invariants auto-track | local; verifier names the rule's two encoders |
| 3 | require approval of the **most recent push** (by a non-pusher) | ~+40 model lines + 14 scenario/flow rebinds | 121 → **434** (×3.6) | reviewer identity required; 4 actions parametrised, 2 split in two; +1 enum, +2 fields, +1 query | **boundary**: not a local edit |
| 4 | **allow bypass** (escape hatch) | +8 to add; full change 23 ins / 9 del | 121 → 181 | adding it FAILs 6/7 queries + 1/2 invariants; re-scoping restores green | cheap to add, detonates every global guarantee |

### 1 — dismiss-stale-on-push disabled

`push_commit` and `update_branch` stop resetting `approvals`/`code_owner_approved`
(they still re-run checks). Cost: 4 insertions / 9 deletions across two actions.

At `check`, `sc_push_dismisses_approvals`, `sc_update_branch` and
`flow_push_forces_reapproval` (at checkpoint 5) go red — the behavioural cases
catch the changed transition at once. But every reachability query and both
invariants stay green and the state count is unchanged (121): the *policy at merge
time* (two approvals + a code owner) is still satisfied; the model cannot express
that those approvals predate the latest commit. This is the same path/temporal
boundary documented above, now confirmed by a change rather than asserted.

### 2 — strict → loose status checks

Drop the `behind_base == False` conjunct from `mergeable`. Cost: one line.

A new reachable state appears (121 → 122: a merge while behind base), and exactly
two artefacts go red — the dedicated guard `never_merge_behind` (the mutation
detector firing) and the negative scenario `sc_merge_behind_base`. The two policy
invariants reference the same `mergeable` predicate, so they move *with* the
relaxed policy and stay green. Relaxing a rule is a one-line policy edit, but the
verifier names the independent objects that still encode the old rule — it never
silently accepts the weaker policy.

### 3 — require approval of the most recent push (the identity boundary)

GitHub's "require approval of the most recent reviewable push" means the latest
push must be approved by *someone other than the person who pushed it*. The
baseline abstraction has no reviewer identity (`approvals` is a bare count), so
this rule is **not expressible without rebuilding around identity**:

- a `Reviewer` enum and a `reviewer` `Param`;
- `last_pusher` and `approved_by_non_pusher` fields;
- `Set` has no conditional form, so `approve` and `code_owner_approve` each split
  into a non-pusher and a self-push variant (guarded by `reviewer != last_pusher`
  / `reviewer == last_pusher`); `push_commit` and `update_branch` become
  parametrised and record the pusher;
- a new conjunct in `mergeable` and a `never_merge_without_non_pusher_approval`
  guard.

Measured: the rule *is* expressible and verifies (the new Unreachable guard holds;
the witness now carries `reviewer=R2`), but the state space grows **121 → 434
(×3.6)** and **14 scenario/flow references** must be rebound to a concrete
`(reviewer, variant)`. This is the honest boundary: "change is cheap" holds for
rules about *what state* a PR is in and breaks for rules about *who* acted —
exactly the composition/identity pressure the second evidence model must target,
and where a tool with first-class actors / temporal logic (Quint, FizzBee) would
likely be cheaper.

### 4 — allow bypass (an escape hatch)

Add a `merge_bypass` action that merges with no `mergeable` guard (an authorised
actor force-merges). Adding it is 8 lines — and the verifier immediately reports
that **6 of 7 queries and 1 of 2 invariants are now false**: every `never_merge_*`
guarantee, `policy_always_holds` and `merged_satisfied_policy` fail, because a
merged state is now reachable through the hatch. Only `merge_is_achievable` and
`code_owner_is_an_approval` survive. The loss of unbypassability is loud, not
hidden.

Restoring meaningful safety adds ~15 insertions / 9 deletions on top of the hatch
(the full change-4 diff is 23 insertions / 9 deletions): a `bypassed` flag set by
the hatch, and re-scoping all seven guarantees to the *normal* merge path
(`merged_normally = MERGED AND NOT bypassed`). The suite is then green again
(121 → 181 states) — but the recovered property is deliberately *weaker* ("no
non-bypassed merge violates the policy"); bypass merges are unconstrained by
construction. That is the true cost of an escape hatch, made explicit in the diff.

### What the series shows

- Two of the four changes are genuinely local (1, 2): a few lines, and the
  verifier pinpoints the blast radius — broken scenarios/flows and the specific
  guards that independently encode a relaxed rule.
- The reachability-only engine has a real ceiling (change 1): it cannot see
  staleness/history, so a behaviour change can leave every reachability query
  green while only scenarios/flows catch it.
- *Who*-based requirements (change 3) are not local — they force identity through
  every actor action and multiply the state space. This is the engine's boundary
  and the brief for the second model.
- Safety-breaking changes (change 4) are caught loudly and at once, and both the
  cost of re-scoping the guarantee and the fact that it genuinely weakens are
  visible in the diff.

`affects PullRequest.approvals` before any of these edits gives the precise impact
radius (writers, readers, invariants, scenarios), so an agent sees what a change
will touch without opening files.

## Agent surface (измерено)

- `affects <field>` — точный кросс-референс read/write/invariants/scenarios. Полезно.
- `show action/lifecycle` — структурированный pre/effect/переходы. Полезно.
- `--what-if <patch>` — **починено**. Раньше single-file spec (`spec.py` без
  `__init__.py`, как coin/cloak/branch_protection) грузился под синтетическим
  именем, и патч не мог его импортировать (`No module named ...`). Теперь
  загруженная spec всегда доступна патчу под стабильным алиасом `analint_spec`
  (`from analint_spec import PullRequest`), независимо от раскладки. Проверено
  CLI и регрессионным тестом `test_what_if_patch_on_single_file_spec`.

## Сравнение с Quint / FizzBee (честно: структурное, не полный порт)

Оба моделируют это как transition system с инвариантами — концептуально то же,
что analint BFS + Unreachable/AlwaysHolds. Различия:

- **Читаемость**: в analint действия (`approve`, `push_commit`, `merge`) и есть
  доменные переходы, а `mergeable` читается как сама политика. Quint/FizzBee —
  `action`/`step` с `any {...}` и guard-выражениями; ближе к коду TLA-стиля.
- **Выразительность/инструменты в пользу Quint/FizzBee**: темпоральные свойства
  (не только reachability — см. границу выше про path-свойства), fairness,
  рандомизированная симуляция, Apalache (SMT), заметно больший масштаб. analint
  — только bounded BFS + reachability-классы.
- **В пользу analint для этой ниши**: `show`/`affects`/`--what-if`,
  авто-инвариант по canonical model, scenario-coverage warnings,
  spec-as-checkable-doc на Python без отдельного языка.

Честный вердикт: для **change-oriented доменной политики** analint конкурентен и
заметно доменно-читаемее; **не доказано «лучше»** без полного порта в Quint и
сравнения authoring-time/найденных дефектов на серии изменений. Это остаётся.

## Нужны ли события? Demand в этом кейсе не обнаружен.

Домен PR review/CI/merge выглядит «событийным» (approve, push, checks, base
moved), но в **выбранной абстракции одной агрегированной PR-политики**
смоделировался полностью через состояние (status-поля), без operational
`on`/event-pool. Это **не опровергает** разворот research/22 и не дал ни одного
повода добавлять event pool.

Но это и **не доказывает**, что события не нужны вообще: один агрегированный
`PullRequest` ничего не говорит про несколько PR / merge queue, асинхронную
доставку с ретраями, audit-subscribers, корреляцию CI-run ↔ head SHA,
at-least-once/exactly-once. Эти нагрузки — задача для второй модели (она должна
бить по composition + bounded multiplicity, а не повторять сильную сторону
текущего движка).

## Статус evidence-gate

- ⏳ две внешние модели — **1 из 2** (эта; вторая должна нагружать composition /
  несколько экземпляров).
- ⏳ full port of the same case to Quint/FizzBee + measuring authoring/diff/defects
  across the change series. So far only a structural comparison; the analint-side
  series is now measured (see "Change series"), but the Quint port and its
  side-by-side are still pending.
- ✅ a series of four requirement changes is measured — dismiss-stale off,
  strict→loose checks, require-approval-of-latest-push, allow-bypass — each with
  its saved diff, state-count delta and blast radius (see "Change series"). Two are
  local one-/few-line edits; change 3 hits the identity boundary (×3.6 states);
  change 4 detonates every global guarantee until re-scoped.
- ✅ single-file `--what-if` починен (стабильный алиас `analint_spec`).
- ✅ source/assumption matrix добавлена (трассируемость к GitHub docs).

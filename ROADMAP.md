# analint — Roadmap

Current status (2026-10-30): **0.0.3 released and verified on PyPI.
Semantic core and P5 are complete.**
analint declares finite system behaviour in Python and checks it through one
transition kernel, canonical initial states, executable scenarios/flows and
property-local reachability. Slicing, compact state storage and the opt-in TLC
backend are released. Incremental successor generation and on-disk exploration
caching are included in 0.0.3 (see `CHANGELOG.md`).

**This file is the single source of truth for status and priorities.**
`research/` contains dated rationale; priorities stated only there are historical.
Internal v0.9–v1.3 milestones below are design phases, not package versions.
Use `uv run pytest --collect-only -q` for the current test inventory rather than
maintaining a second test count here.

## Current priorities (2026-10-30)

The documentation baseline is complete: a runnable first-spec tutorial,
verification concepts, DSL/CLI/MCP references and examples gallery. Pull requests
and main pushes now have a strict documentation build and executable tutorial
checks before the existing main-only deployment.

1. **Real-spec feedback — next.** Use published 0.0.3 on project models and
   record any remaining inconclusive properties or repetitive DSL workarounds.
   Prioritize concrete reproductions over speculative engine work. The release
   itself is complete: GitHub Release, Trusted Publishing and a fresh PyPI
   installation with the MCP extra have all been verified.
2. **Additive DSL cleanup — deferred, independently scoped.** `Key(...)`, explicit
   canonical scope presence and fixed-only `Initial(given=...)` remain open.
   Existing `Initial.given` can fix values alongside a non-empty `vary`; it does
   not yet support a fixed-only relation. Design the new surface across the
   interpreter, compiler, slicing, cache, artifacts and TLC before implementation.
   This work is independent of the 0.0.3 release.
3. **Performance — acceptance complete.** P5 and issue #3 are closed. Default to
   slicing plus compact storage; use `--cache` for repeated checks and `--tlc`
   for supported inconclusive properties. Further engine work requires a measured
   bottleneck; product-sized coupled cones are first a modelling question.

New semantic primitives remain evidence-gated. Liveness/fairness, automatic event
dispatch, unbounded structures, a general implementation bridge, a separate
semantic-diff command and a Rust core remain outside the current work.

---

## Сценарии использования (от них выведены фазы)

Пользователи: AI-агент, человек (аналитик / гейм-дизайнер / разработчик), CI.
Спека живёт в своём репозитории (или каталоге монорепо); сервисы — в своих.

### A. Ориентация — «узнать, прежде чем трогать»

Агент получил задачу «карточки можно архивировать только владельцу доски».
Прежде чем менять описание системы, он спрашивает:

```
analint show                      # обзор: сущности, действия, жизненные циклы
analint show action archive-card  # pre/effects/события конкретного действия
analint affects Card.status       # что задевает это поле: действия, правила,
                                  # сценарии, переходы — радиус удара изменения
analint check                     # scenarios + объявленные verification queries
```

### B. Моделирование изменения — «гипотеза → согласованность»

Агент (или человек) правит спеку: новое pre-условие, новое действие, новая
сущность. Итерирует до зелёного:

```
analint check                     # структурные проверки + прогон сценариев
analint check --what-if patch.py  # проверить гипотезу, не трогая файлы
```

Коммит спеки. Пока semantic diff отложен, агент ревьюит Python diff и
сравнивает verification results двух ревизий. Это полезная временная практика,
но не эквивалент semantic diff: новый переход может не изменить существующие
verdicts.

### C. Распространение на реализацию — отложено

Bridge к реализации (MBT/trace replay/runtime conformance) не является текущей
фазой. Вернуться к нему стоит после стабилизации transition semantics и
подтверждения спроса на реальных моделях.

### D. CI-гейт

В репозитории спеки: `analint check --format json` на каждый PR. До исправления
v1.3 CI не должен трактовать `INCONCLUSIVE` как PASS. Интеграция с
репозиториями сервисов отложена вместе с bridge.

### E. Холодный старт

`analint init` — каркас спеки; в будущем `init --from-code` — агент майнит
черновик модели из существующей кодовой базы, линтер и человек верифицируют.

---

## Фазы

### v0.9 — Реформа DSL + корректность загрузки ✅

Сделать до публикации: нельзя публиковать имена, которые сразу переименуем.
Семантика рантайма не меняется — это переупаковка поверхности (research/05, 07).

- `UseCase` → `Action`; `BusinessRule`/`RuleType` исчезают: голые предикаты в
  `pre=`/`post=`, мировые инварианты — `Invariant(expr)`
- `effects=`/`do=` → `effect=` с **одновременной** семантикой: правые части
  на пред-состоянии, порядок не значим, два эффекта на одно поле — ошибка
  (фикс `_apply_effects`: резолв против `context`, не `post`)
- `StateMachine` → `Lifecycle` (+ `terminal=[...]` — сахар «терминальное
  состояние блокирует действия»)
- События с payload: `emits=[CardMoved(card_id=Card.id)]`, `triggered_by` → `on`,
  pre над полями события; проверка типов биндинга
- `Implies(a, b)`; id опциональны (выводятся из имени переменной)
- **Лоадер: точка входа + реестр** вместо обхода файлов — чинит подтверждённый
  баг двойного импорта (research/09): классы сущностей дублируются в спеке
- Новый пример `examples/cloak/` (Cloak of Darkness — бенчмарк из research/06)
- Старые имена — deprecated-алиасы на один релиз; README/AGENTS.md обновить

### v0.10 — Агентская поверхность (сценарии A, B без движка) ✅

Реализуемо статически, по уже собранной модели (research/08 §5):

- `analint show [entity|action|lifecycle ...]` — структурированный вывод, JSON
- `analint affects <Entity.field | action-id>` — кросс-референс: кто читает,
  кто пишет, в каких сценариях участвует
- `analint check --what-if <file>` — проверка гипотезы без записи
- Говорящие exit-коды, краткий `--format json` везде (контекст агента дорог)
- MCP-сервер поверх того же ядра (тонкая обёртка CLI-команд)
- Раздел в AGENTS.md: как агенту работать со спекой (цикл A→B→C→D)

### v1.0 — Движок: bounded reachability (research/04) ✅

Превращает линтер в верификатор. Состояние = кортеж полей; enum'ы конечны,
числовые поля требуют явных границ (без границ — честная деградация до
snapshot-режима).

- BFS по достижимым состояниям; **трасса-контрпример** как формат ошибки
- Запросы: `Reachable(p)`, `Unreachable(p)` (метки «система не должна уметь
  сюда попадать» — регрессии ловятся диффом), `NoDeadEnd(goal=p)`,
  `AlwaysHolds(p)`, `DeadActions()`
- ✅ CLI `analint explore` / `analint trace` реализованы в P4.2/P4.3 (exploration
  artifact + state-diff witness traces)
- ⏸ реляционные эффекты `f.next` — слой для недетерминизма (выбор игрока,
  успех/отказ платежа) без отдельного примитива Choice (research/07)
- ⏸ `analint simulate --steps N` — случайные блуждания как smoke-test спеки

### v1.0.1 — Реформа уровня поля (research/13) ✅

- `Lifecycle(...)` объявляется прямо на поле сущности; отдельные переменные
  lifecycle и обратный `field=` удалены
- `Field(default, ge/gt/le/lt, saturate)` объединяет в одном месте валидацию
  экземпляра, post-state constraints и числовые границы explorer; `Bounds`
  удалён
- примеры используют `StrEnum`; `Transition.to_states` всегда коллекция и
  хранится как неизменяемый tuple
- добавлены базовые `Predicate`/`Effect`, generics для
  `Lifecycle[S]`/`Transition[S]`, публичные модели получили предметные типы

### v1.1 — Семантический дифф + мост к коду — ⏸ ОТЛОЖЕНО (13 июня 2026)

Понижено разворотом от 13 июня 2026 (research/17 §3). Причина: фокус смещён на
полноту движка; связывать спеку с реализацией — отдельный вопрос «нужно ли и в
каком виде», авансом не строим. Временный proxy-сигнал — прогнать верификатор
на двух git-ревизиях спеки и сравнить результаты; агент дифает коммиты самой
спеки. Это не эквивалент semantic diff: расширение поведения может не изменить
существующие verdicts. Условия возврата наверх — в research/17 §3
(«Как откатиться»).

Исходный план (заморожен):

- `analint diff <git-rev>` — дифф уровня модели: действия/переходы/инварианты,
  изменения достижимости, нарушенные `Unreachable`
- Пин версии спеки в репо сервиса (`analint.pin`: repo+commit) + проверка
  «спека ушла вперёд» → сигнал к сессии сверки, дифф — рабочий наряд
- Системный слой (крупнозернистый): `Service(repo=..., implements=[checkout])`
  в репо спеки — питоновские ссылки, не строки; дифф сообщает задетые сервисы
- Шаблоны CI (GitHub Actions) для репо спеки и репо сервисов
- По спросу: генерация скелетов конформанс-тестов из сценариев — в тестовый
  каталог сервиса, боевой код остаётся чистым

### v1.2+ — Выразительность (по спросу, не авансом)

- ✅ Параметризованные действия (`Param`, `params=`/`where=`/`bind()` —
  по итогам перевода Quint, research/15)
- ✅ Арифметический AST (`Wallet.balance - Order.total >= 0`, именованные
  выражения, канон эффекта `Set(field, expr)`)
- ✅ Конечные множества начальных состояний (`given_any` + multi-root BFS,
  research/16; прототип — мафия с квантификацией по расстановкам ролей)
- ✅ Bounded multiplicity, ступень 1: `Scope(Entity, keys=[...])`, стабильные
  `InstanceRef`, адресуемые поля экземпляров, `Param` по экземплярам,
  scenario runner и explorer над несколькими объектами одного типа
- ✅ `Bound` + конечные `ForAll/Exists` над bounded scope: явные AST-узлы,
  вложенные кванторы, использование в invariants/actions/scenarios/queries
- ✅ `Count/Sum/Min/Max` над scope: арифметические AST-узлы, композиция с
  выражениями, использование в эффектах и reachability
- ✅ Declarative initial relation: `Initial(vary=..., where=...)`, конечные
  домены из bool/Enum/Field, коррелированные predicates, bounded expansion
- ✅ Presence в фиксированном universe: `Absent(ref)` snapshots,
  `Present(ref/bound/param)`, quantifiers/aggregates только по present slots
- ✅ `Create/Delete` effects внутри фиксированного universe (путь Alloy;
  research/01, 06, 14, 16): next-state факты о присутствии слота, симметричные
  `Set`; pre-state guards (absent для Create, present для Delete), конфликты
  одновременности (двойной flip присутствия, presence+field на одном слоте),
  Field-ограничения и saturation на созданных инстансах, участие в
  reachability/quantifiers/aggregates
- ✅ Композиция спек через явные версионированные `Contract`: один root
  `Spec(imports=[...])`, identity-dedup, строгие коллизии id, без утечки
  приватных объектов из import graph; несколько `Spec` больше не сливаются
  неявно; `show contract` и `--what-if` работают поверх composed model
- `Computed(...)` — производные поля; guards на переходах Lifecycle
- Доменные профили-словари: `analint.narrative` (Scene/World/Character),
  `analint.systems` (Service/Operation) — алиасы, не форки (research/05)

### v1.3 — Semantic core — complete (P0–P4; P5 accepted 2026-10-12)

Базовая петля «описать систему → узнать, согласована ли она» должна работать
надёжно и без церемоний. Research/18 уточняет порядок после проверки кода.

#### P0. False-green и единый transition kernel

- ✅ `INCONCLUSIVE` даёт общий трёхзначный `verdict` и non-zero exit (код 4),
  никогда `passed: true` (research/18 §2.2); fail-closed агрегация статусов
- ✅ explorer проверяет `Action.post`, включая effectless actions (research/18
  §2.1, review 584d819)
- ✅ pre-kernel gate сыграл свою роль: normative strict-xfail фиксировали
  известные delta до рефактора и снимались по мере их закрытия; сейчас
  `test_transition_conformance` — чистый agreement-spec без xfail. Accepted
  transitions сравниваются по post-state; characterization фиксирует graph,
  traces, findings, roots, fired/excluded и completeness
- ✅ единый `validator/kernel.py` `step(spec, action, context)` для scenario,
  explorer и будущего executable Flow: одинаковый pre/effect/post, Field,
  Lifecycle, terminal/presence guards, emitted-payload, единый ordering.
  Инварианты намеренно вне `step` — это предикат состояния, применяемый каждым
  путём на уровне state (root/successor в explorer, pre/post в scenario), что
  сохраняет post-invariant witness-edge
- ✅ `TransitionResult`: outcome (`ACCEPTED/REJECTED/DEFECT`), post-context,
  findings, materialized events, changed fields/state diff, `entered`
- ✅ все 5 расхождений scenario↔explorer закрыты: lifecycle-переход в scenario,
  pre-eval-error → DEFECT, terminal `Delete`, emitted payload, и pre-state
  invariant → DEFECT. Принято решение «illegal state → нет исходящих рёбер»
  (review ca537a2): невалидный root/successor остаётся witness, но не
  разворачивается. `examples/taskboard` исправлен — активность исполнителя стала
  precondition `acting_user_is_active`, а не бутафорским мировым инвариантом
- ✅ прямые unit-тесты `step()`/`TransitionResult` (`tests/test_kernel.py`):
  agreement двух callers не ловит общее сломанное поле, поэтому result
  проверяется напрямую — outcome, post-context, changed_fields, emitted, entered

#### P1. Canonical model и verification policy ✅

- ✅ spec-level `Spec.initial: Initial | None` — канонический initial state(s);
  query без собственного источника (given/given_any/initial) падает на него,
  `None` = single root из defaults. `_auto_populate` сохраняет его. Валидируется
  и по форме (общий `_validate_initial` для vary/where/given), и по построимости
  (строится один раз через `build_canonical_initials`, ошибка → `spec:<id>` ERROR
  независимо от наличия consumers); `Spec.max_states` ограничивает бюджет (gt=0)
- ✅ invariants автоматически проверяются по reachable states canonical model
  (`verify_invariants`): отдельная секция `InvariantResult` со статусом
  PASS / FAIL+trace / INCONCLUSIVE (cap) / NOT_CHECKED (нельзя построить
  canonical state space или инвариант нигде не вычислялся) — не зависит от
  наличия `AlwaysHolds` query; mafia демонстрирует проверку под каждой
  расстановкой ролей
- ✅ статус отдельной проверки (query/invariant) четырёхзначен —
  `PASS / FAIL / INCONCLUSIVE / NOT_CHECKED`; общий `Verdict` остаётся
  трёхзначным (`PASS / FAIL / INCONCLUSIVE`), куда NOT_CHECKED агрегируется как
  INCONCLUSIVE. Секция инвариантов влита в fail-closed агрегацию, terminal/JSON
  репортеры и characterization; canonical exploration findings (включая
  transition defects) не теряются, а попадают в общий verdict
- ✅ `NoDeadEnd` остаётся явным: без `goal` softlock определить невозможно
- ✅ dead actions / недостижимые lifecycle edges — explicit queries, не
  универсальные hard requirements

#### P2. Исполняемый многошаговый trace

- ✅ `Flow` оживлён: `given` (initial state) + смешанный `steps` (Action |
  Assert | Emitted). Каждый шаг-Action идёт через общий `kernel.step`,
  post→pre; первый rejected/defect action или ложный checkpoint валит flow с
  трассой. Исторически Flow без `given` оставался документацией; этот режим
  удалён pre-release cleanup из block C ниже. `FlowResult` влит в verdict,
  warning-агрегацию, terminal/JSON репортеры и characterization; `validator/flow_runner`
- ✅ post-state шага становится pre-state следующего через общий transition kernel
- ✅ «слои» как arbitrary snapshot deltas НЕ добавлены: только реальные действия
  через kernel (preconditions всегда соблюдены)
- ✅ exploration result artifact (roots/nodes/edges/findings/traces, completeness,
  summary) как основа CLI/MCP/визуализации — done as P4.1 (`analint.exploration/v1`)

#### P3. Семантическая честность словаря

Историческое решение (reviews/8cca900) сначала оставляло `by`/`on`/`requires`
как documentary metadata; pre-release cleanup из block C ниже удалил их.
Операционный `on` остаётся отложен за evidence-gate
(research/22 §«Разворот»: мультимножество-пул не ограничен конечным payload;
consume меняет смысл `Event`; ломает state-chaining саги; нет внешних моделей).

- ✅ `Actor/by`: были documentary metadata (не authz); удалены в block C.
- ✅ `Event/emits/on`: `emits` — поведение (материализация payload + `Emitted`);
  `on` был documentary (не trigger; причинность через состояние), затем удалён.
  Формулировки
  без «triggers/subscribe» во ВСЕХ поверхностях: docstrings Action/Event, README,
  structural warning, **и agent-facing API** — `affects` JSON отдаёт
  `documented_handlers` (был `triggers_downstream`), MCP-описание переформулировано
  (закрыто ревью 4465e16)
- ✅ `requires`: был Flow-ordering documentation, не операционный prerequisite;
  удалён в block C.
- ✅ предупреждение о потенциально безграничных числовых доменах (2026-10-11):
  only on a capped exploration, naming the slice's fields that actions change
  arithmetically with no Field bound in that direction; otherwise the hint is
  "raise max_states" (plus `--tlc` where TLC can decide the check)
- ⏳ операционный `on` (event dispatch) — только при подтверждении внешним
  evidence-кейсом, что state-протокола недостаточно (research/22 пункты 1–5)

#### Evidence gate (параллельно с P0, блокирует новые примитивы)

- ✅ two externally documented system models, not systems invented for analint
  — **2 of 2**:
  ✅ `examples/branch_protection` (GitHub protected PR policy, research/23,
  with a source/assumption matrix and fidelity fixes after review 4465e16);
  ✅ OAuth 2.0 Authorization Code + PKCE (`examples/oauth`, research/24):
  two clients, two code/token scopes, interception, relational provenance,
  replay revocation, and a no-semantic-change multi-file `Contract` split;
  complete graph: 1169 states / 2256 edges
- ✅ the same bounded OAuth case is ported to Quint 0.32.0
  (`examples/oauth/oauth.qnt`): typecheck + 5 run tests + seeded 10k-trace
  safety simulation pass, AND symbolic `quint verify` (Apalache, `allSafety`,
  12 steps) passes — `[ok] No violation found`. This is an independent bounded
  safety cross-check, not proof of graph equivalence with analint's complete
  1169-state exploration: the Quint model includes stuttering and no diameter
  proof was established. One tool-semantics finding: Apalache flags
  terminal/quiescent states as a deadlock, so the Quint `step` gained a
  safety-preserving stutter (research/24)
- ✅ a series of four requirement changes is measured (research/23 "Change
  series"): dismiss-stale off, strict→loose checks, require-approval-of-latest-push,
  allow-bypass — each with its saved diff, state-count delta and blast radius. Two
  are local few-line edits; change 3 hits the identity boundary (×3.6 states,
  reviewer identity required); change 4 detonates every global guarantee until
  re-scoped. Change 1 also shows that path history is invisible when the model
  does not reify it as state; this motivates explicit abstraction choices, not a
  claim that reachability can never model historical facts
- ✅ первый внешний change-oriented candidate реализован: GitHub protected
  pull-request policy (approvals, stale reviews, status checks, code owners).
  В **этой абстракции** (одна агрегированная PR-политика) события не
  понадобились — не опровергает разворот research/22; demand на event pool не
  обнаружен (multi-PR/merge-queue/async remain candidates for a future model)
- ✅ **synthesis verdict (research/25):** the gate is passed and the evidence did
  not demand a new verification primitive. Freeze **semantic expansion**, not
  development of the self-contained engine. Bounded reachability remains the
  current scope; correctness, diagnostics, exploration artifacts, reductions and
  measured performance remain active core work. A Quint exporter is not on the
  active roadmap: it cannot export temporal questions absent from the source DSL,
  would create a second semantic implementation, and does not advance the goal of
  a self-contained framework.
- event pool, time/concurrency primitives, `Computed`, refinement/overlays —
  remain gated on repeated real-evidence pain, which the two models did not produce

#### P4. Self-contained model workbench — ✅ complete

Detailed implementation contract, JSON shape, tests and commit checkpoints:
research/26.

- ✅ **P4.0a type-boundary gate:** audit the intentional dual view
  (`wallet.balance` is a domain value; `Wallet.balance` is a symbolic reference),
  Pylance/Pyright metaclass opacity, collection invariance, AST operand unions,
  `Any` and suppressions. Do not expose private `FieldDescriptor` types or assume
  `balance: int` is wrong
- ✅ **P4.0b DSL typing policy:** preserve annotation-first declarations such as
  `balance: int`; improve constructor/collection typing where possible and
  document narrow IDE inspection settings for unavoidable class-level DSL false
  positives. Descriptor-first syntax and a parallel field namespace are rejected
- ✅ **P4.0c example intent:** `examples/expectations.toml`, a README for every
  example, complete root README inventory, and a test that checks expected
  verdicts/failures/warnings separately from characterization snapshots
- ✅ **P4.1 artifact core:** deterministic `analint.exploration/v1` DTO and
  converter over the existing `Exploration`; stable nodes/edges/bindings/diffs,
  summary and explicit multi-reason completeness
- ✅ **P4.2 exploration service:** canonical/query-specific exploration through
  compact-by-default CLI and MCP; full graph is explicit and never silently
  truncated
- ✅ **P4.3 witness diagnostics:** state-diff traces for query
  witnesses/counterexamples while preserving the existing action-id trace
- ✅ **P4.4 measured scaling:** generated counter-grid, conserved-transfer and
  workflow-product families over 10²–10⁵ states; profile before optimization,
  one semantic-neutral change per commit. Also measure/address that compact &
  MCP-guarded output still builds the full artifact internally (review of 4b5535d)
  — consider a summary-only/lazy builder so compact output does not materialise the
  whole graph
- ✅ **P4.5 project-sized dogfood:** one externally documented model with at
  least three interacting entity types/scopes, ten actions and a measured
  requirement-change series

Success criterion: a user or agent can model a non-trivial project, understand
the explored behavior and counterexample state changes, and receive an honest
completeness verdict using analint alone.

### Ecosystem — first public release (0.0.1), complete

Plan: research/29. Unblocked now that the P4 workbench is complete.

- ✅ **Packaging metadata + license:** MIT `LICENSE`; `pyproject` `version=0.0.1`
  (reset from the internal 1.0.1 milestone numbering), `license`/`authors`/
  `readme`/`keywords`/`classifiers`/`[project.urls]`; `requires-python` relaxed
  `==3.14.*` → `>=3.12` (the real floor is PEP 695; `examples/play.py` backported
  off PEP 758 so 3.12 is honest — proven by the full suite passing on 3.12; ruff
  `target-version` and ty `python-version` also dropped to 3.12, else `ruff
  format` keeps stripping the except-group parens back to 3.14-only syntax);
  sdist target excludes `research/`/`reviews/`, ships `src`/`examples`/`tests`
- ✅ **Docs:** README License/Status sections; `CONTRIBUTING.md`; `CHANGELOG.md`
  (Keep a Changelog, 0.0.1 entry honest about bounded-reachability scope)
- ✅ **Build/install validation:** `uv build`, `twine check` (both PASSED), clean
  wheel install + CLI smoke test on Python 3.12
- ✅ **CI Trusted Publishing:** `.github/workflows/publish.yml` (OIDC, no tokens) —
  `workflow_dispatch` → TestPyPI, GitHub Release → PyPI
- ✅ **TestPyPI dry-run:** OIDC pipeline green end-to-end. Surfaced two real bugs
  the dev lock had masked (Typer 0.26.0 vendored Click; lock was pinned to 0.25.1,
  see research/29): (a) `cli.py` imported external `click` — removed, the CLI is
  Typer-only, `click` is now dev-only; (b) the `analint <PATH>`→`check` shortcut
  caught the wrong `UsageError` class — rewritten to inspect args, regression-tested.
  Also `uv lock --upgrade` so dev/CI run the versions users install
- ✅ **CI version matrix:** `quality.yml` split into `lint` (once) + `test` on
  Python 3.12 / 3.13 / 3.14 — CI now runs the whole supported range, not just the
  one locked version that masked the Typer boundary
- ✅ **`py.typed` marker:** ship the PEP 561 marker so the `Typing :: Typed`
  classifier is honest and downstream type-checkers use analint's inline types

**Release follow-up:** 0.0.1 and 0.0.2 are published. The completed review below
unblocks documentation; the remaining additive work is independent.

- **A. Release-engineering hardening** (auto-catch the class of bug we hit manually) ✅
  - ✅ CI `package` job: clean-room `uv build` → install the wheel into an env
    *without* dev deps → smoke-run `analint --version` / `analint check`, across
    the 3.12/3.13/3.14 matrix. The Click/Typer breakage is now a CI gate
  - ✅ CLI `--version`; `__version__` derived from installed metadata (was a stale
    hardcoded "1.0.1"); a test asserts no drift
  - ✅ README badges: CI, coverage (Codecov), supported Python, license. PyPI
    version badge deferred to the publish step. **User action:** enable the repo
    at codecov.io (public repos usually tokenless; else add a `CODECOV_TOKEN`
    secret) so the coverage badge populates
> **Sequencing update (2026-10-30):** the June API-review gate is satisfied.
> MkDocs Material and deployment already exist; the documentation baseline below
> is now complete.
> The additive DSL pass remains independently deferred.

- **C. Abstraction / public-API stabilization — complete for documentation**
  - [x] Thorough review of the core abstractions and the public surface: are the
    DSL primitives (`Entity` / `Action` / `Invariant` / `Flow` / `Scope` /
    `Contract` / `Lifecycle` / queries …), the `analint` export set / `__all__`,
    naming, and the CLI / MCP / exploration-artifact contracts the right and stable
    shape? Could any need a *big* change before 1.0? Verdict and evidence:
    research/30.
  - [x] Record the verdict: the semantic kernel is stable; do not replace it with
    a textual, logic-programming, YAML or controlled-natural-language DSL.
    The current public surface still needs one bounded pre-doc cleanup.
  - [x] Strict goal/expressiveness closure audit (research/31): every intended
    first-release model reduces to a finite state-transition abstraction covered
    by the current DSL; no new semantic primitive is required. Liveness/fairness,
    real event delivery/time/probability, unbounded structures and intra-action
    concurrency remain explicit non-goals.
  - [x] **Corrected `NoDeadEnd` publication claims** (recoverability, not
    liveness): renamed `saga_always_settles` → `settlement_always_reachable` and
    reworded the fulfillment "always settles"/"every run terminates"/"never
    wedges" prose; the engine docstring/reporter were already honest. The
    characterization-snapshot diff was purely the query-id key (commit 9a9f190).

  **Decision (2026-06-20, after the strict review pass):** split the cleanup into a
  pure-subtractive **core** (first, one reviewable pass, **no deprecation aliases**
  — nothing is on PyPI yet) and a **decoupled additive** pass. Two of research/30's
  recommendations are deliberately **not** taken:
  - **Do NOT narrow lifecycle `terminal`.** Whole-entity freeze is a useful,
    intuitive default ("CANCELLED order / ARCHIVED card / MERGED PR is frozen"); no
    current example needs post-terminal mutation or has multiple lifecycle fields.
    Narrowing is speculative, high blast-radius (re-characterizes 9 examples) and
    makes the common case more verbose. Treat the "surprise" as documentation:
    state the whole-entity rule precisely. Revisit only with a real model that needs it.
  - **Keep `Assert` optional, do not delete it.** Drop it where the list is
    homogeneous (`Scenario.then`) — the bulk of the ~113 uses — but keep `Assert`
    exported and usable in mixed `Flow.steps`, where it is a real reader cue (same
    rationale that keeps `Emitted` and `Add`/`Subtract`).

  - [x] **Subtractive core (commits e03efb8..afbff6c):**
    - remove `Actor` / `Action.by`, `Action.on`, `Action.requires` and the
      documentary-only `Flow` mode (`given=None`); a principal is scoped
      state/`Param`, prose goes in `name`/`description`/`tags`
    - raw predicate checkpoints in `Scenario.then` (drop `Assert` there); keep
      `Assert` optional in `Flow.steps`
    - normalize boolean field refs in predicate positions (remove `== True/False`
      + the spec-wide E712 exception); `And`/`Or`/`Not`/`pre`/`post`/`then` admit
      `bool`, literal bools handled/rejected explicitly
    - lifecycle transition mapping (`transitions={s: [...]}`) instead of the public
      `Transition` wrapper; do not infer terminal from missing keys
    - no deprecation aliases; migrate examples/tests + snapshot in the same pass;
      document the whole-entity terminal rule precisely (no semantic change)
  - [x] **Freeze agent contracts:** every machine-facing JSON now carries a
    `schema` id (`analint.check/v1`, `.overview/v1`, `.show/v1`, `.affects/v1`,
    `.trace/v1`, `.error/v1`; exploration was already `.exploration/v1`); `q.show`
    is shared by CLI and MCP so `show <kind>` without a name behaves identically;
    `--format` is a validated enum (invalid → usage error, no silent terminal
    fallback); stale descriptions fixed (no `actor` in `show` help, MCP says five
    tools). Regression-tested; characterization snapshot unaffected.
  - [ ] **Additive pass — deferred to a future release (new public surface):**
    `Key(...)` scope-key value expression + explicit canonical scope presence +
    fixed-only `Initial(given=...)` (currently `vary` must be non-empty). Removes
    the parallel-identity-param workaround in OAuth/Kubernetes but ADDS a
    symbol/AST node — design and version its
    JSON/artifact representation carefully. Does not gate the subtractive core or docs.
  - [x] Migrate examples/tests and confirm the subtractive `__all__`. **C is
    complete for documentation purposes** — the contract (DSL surface + agent JSON
    schemas) is settled for documentation; the additive `Key` pass is deferred
    beyond 0.0.2 and does not gate docs (block B).
- **B. Documentation — complete (2026-10-30)**
  - [x] MkDocs Material configuration, GitHub Pages deployment and agent guide
    (`mkdocs.yml`, `docs/agents.md`, `.github/workflows/docs.yml`)
  - [x] Dedicated landing page and runnable first-spec tutorial (`docs/index.md`,
    `docs/getting-started.md`), including a planted missing-effect counterexample
    and a packaged what-if exercise that leaves the root unchanged
  - [x] DSL reference (`docs/dsl.md`) and CLI/MCP references (`docs/cli.md`,
    `docs/agents.md`) matching implemented signatures, including the CLI/MCP
    differences and versioned JSON schemas; cache availability marked since 0.0.3
  - [x] Verification concepts (`docs/concepts.md`): bounds, canonical roots,
    verdicts, slices, cache, TLC limits and recoverability versus liveness
  - [x] Examples gallery (`docs/examples.md`), with README links and intended
    failures checked against `examples/expectations.toml`
  - [x] Strict build and executable documentation checks on pull requests and
    main pushes; deployment needs the successful build and is main-only.
    `tests/test_documentation.py` executes the Markdown source through CLI and
    MCP, checks the counterexample/root isolation and verifies the gallery.
- **D. Pre-flight, then publish**
  - [x] Final package validation: full CI matrix, wheel/sdist build, Twine metadata
    check, and clean Python 3.12 install. The old TestPyPI `0.0.1` predates the
    final API cleanup, so the current artifacts were validated locally and in CI.
  - [x] Published `v0.0.1` through the GitHub Release workflow and PyPI Trusted
    Publishing; verified `uvx --from analint==0.0.1 analint --version`.
  - [x] Released `v0.0.2` (2026-10-11) the same way: slicing, R4, `--tlc`,
    invariant traces; breaking explicit composition root (research/35).
    Verified `uvx --from analint==0.0.2 analint --version`.
- **0.0.3 release — complete (2026-10-30)**
  - [x] Validate and describe exploration caching, incremental successor
    generation and documentation; version/lockfile are 0.0.3 and release notes
    are finalized in `CHANGELOG.md`
  - [x] Wheel/sdist build and strict Twine checks; lint, format, typing and strict
    documentation build; clean wheel installs on Python 3.12, 3.13 and 3.14
    verify version, PASS/FAIL/INCONCLUSIVE exits and fresh/cold/warm cache parity
  - [x] Clean optional-MCP installs discover all five tools on 3.12–3.14.
    Fresh installation exposed incompatible MCP SDK 2.x; the extra now requires
    `mcp>=1.0,<2`, matching the server's FastMCP API. CI checks tool discovery
  - [x] Source archives now include the benchmark Python models and scripts
    required by their tests. Archive test collection is a CI gate; the extracted
    candidate's full suite passed on clean Python 3.12 (579 passed, 15 expected
    skips, including TLC conformance where exportable)
  - [x] Published [v0.0.3](https://github.com/angru/analint/releases/tag/v0.0.3)
    from `4eef653` through the existing Trusted Publishing workflow. Fresh
    Python 3.12 installation from PyPI (`analint[mcp]==0.0.3`) verifies version,
    PASS/FAIL/INCONCLUSIVE exits, cache parity and invalidation after an edit,
    invariant counterexamples and discovery of all five MCP tools
- [x] **Agent onboarding:** ship one portable, instruction-only `analint` skill
  in `skills/analint`; scripts, product-specific plugins and bundled MCP
  configuration remain deferred until installation friction or marketplace
  demand is observed.

Explicitly NOT blocking 0.0.1: logo, exhaustive tutorials, autodoc API dump,
coverage gate, Dependabot — all can follow the first release.

Still deferred until later:
- Additional verifier backends beyond the implemented TLC fallback require a
  concrete consumer; standalone Quint ports remain comparison evidence
- State-diff traces and statistics are implemented; Mermaid/DOT visualizations
  for lifecycle/action dependencies remain deferred
- **Optional human TUI (research/32):** not a first-release item and not an
  agent/CI surface. Reconsider after API/docs stabilization only if repeated
  human use shows navigation or trace-review pain. Start read-only in this
  repository over `show`/`affects`/validation/`analint.exploration/v1`, behind an
  optional dependency; no editor or full state graph. Interactive
  enabled/disabled-action stepping is a later milestone.
- **Performance history (research/32):** generated counter-grid,
  conserved-transfer and workflow-product families over 10²–10⁵ states already
  measure one revision. Add a small ASV suite over the same generated workloads
  plus complete validation of representative examples, so runtime and memory can
  be compared by commit on one controlled runner. Keep normal tests free of
  timing gates; use `asv continuous` for performance-sensitive changes and
  scheduled/manual history. Known harness distortion is removed:
  characterization now shares equivalent query explorations, and
  `scripts/bench.py` now ignores non-example directories and includes invariant
  state counts (2026-10-09). Optimize or design
  another backend only from measured scaling/property/consumer triggers.

### P5. Property-local verification + broker benchmark — ✅ DONE (2026-10-12)

Trigger: angru/analint#3 (independent lifecycles → whole-spec BFS pays for
their product; local checks INCONCLUSIVE). Diagnosis, slice contract, sources
and the Quint bake-off protocol: research/34. 0, A–D, R4 and R6 are done; the E
decision (research/36 §4) is accepted on the private spec, and #3 is closed.

- **0. Explicit composition root (research/35; reopens the research/30 freeze
  of `Contract`/`Spec`)** — before B1, so the broker
  model is written as one `Contract` per process. The model is exactly what
  `Spec` and its `Contract`s reference: no globals scan for membership and no
  per-field mixed mode. Entities, events, lifecycles and scopes are derived by
  reference closure. Ids come from a naming pass over members only. Objects
  defined but not in the model get an orphan warning; `--what-if` keeps
  merging its file. Steps: naming pass + orphan warning → reference closure →
  migrate examples one by one (characterization-gated) → remove
  auto-population (breaking, 0.0.2) → docs/skill. ✅ step 1 (naming pass +
  orphan warning, e3611a5; also fixed unnamed composed `Param` action ids).
  ✅ step 2 (2026-10-10): reference closure — entities, events, scopes and
  inline lifecycles are derived from listed behaviour (also after a what-if
  merge); characterization snapshot unchanged; "not registered" probes now
  assert derivation, a second `Scope` per entity is still an error.
  ✅ step 3 (2026-10-10): every example lists its behaviour (taskboard as
  per-process contracts). Snapshot unchanged except three reviewed R7 witness
  reorderings (branch_protection, k8s_replicaset), and all examples also
  match it under a no-scan emulation of step 4. Migration found and fixed two
  engine gaps: listed `Param` declarations orphaned in auto mode, and
  `--what-if` objects dropped by explicit lists. A third, a what-if merge
  leaking into the cached composed root, was fixed on main as well.
  ✅ step 4 (breaking, 0.0.2): no scan, no mixed mode, "empty model" error;
  snapshot unchanged. Reviewed and merged to main on 2026-10-10 (a9f89aa).
  ✅ step 5: README/AGENTS.md/CHANGELOG and the agent skill (explicit
  listing, orphan warning, slices, `--max-states`/`--no-slice`)
- ✅ **A. Engine hygiene** (f9fe90c..8e96ad3): shared canonical exploration,
  state-key layout, cached guard plan/invariant keys, silent rejections,
  trace-on-defect, copy-on-write effects, `deque` — ~5× on
  `independent_lifecycles` with identical verdicts (table: research/34 §8);
  `INCONCLUSIVE`/`NOT_CHECKED` split in summaries; `check --max-states`.
  ✅ Per-check `elapsed_ms` (2026-10-09): JSON + terminal, incremental wall time
  including slice retries; shared exploration charged to its first consumer.
  Invariants with no canonical roots omit timing; setup and action coverage
  outside a check are excluded.
- ✅ **B1. Broker model M1–M3** (`examples/broker`, one `Contract` per process):
  33 actions, all PASS; verification slices stay at 22 states from M1 to M3,
  and the genuinely coupled money model is ~16k states. It exposed two slice
  artefacts (terminal-lock reads, invariants as constraints), both removed
  exactly (research/34 §5, §8)
- ✅ **B2. Bounded broker M4–M6 fixtures and measurements** (2026-10-10) —
  leverage/margin/stop out, partners and multiplicity; measured at 2k/10k
  with and without slicing. This completes the increment/measurement work,
  **not** exhaustive verification of the composed model or financial-ledger
  consolidation. Exact total graph size remains unknown (budget exhausted).
  - ✅ Prerequisite found while modelling M4 (2026-10-10): quantified and
    aggregate invariant applicability now follows present members, while direct
    absent-slot reads still skip the invariant. Empty Min/Max remains an error.
    Presence-layout caching preserves the static fast path. The only baseline
    delta is 20 broker scenario rule counts (+4 formerly skipped empty-domain
    checks); verdicts, findings, graph hashes and traces are unchanged.
  - ✅ M4 model implemented as `benchmarks/broker/m4.py` (2026-10-10): seven
    entities, 93 expanded actions, 58 scenarios and two flows; leverage,
    high-margin caps, class-dependent margin buckets, ordered stop out and
    negative-balance protection. M1–M3/Quint remain the fixed baseline. Risk
    equity is a separate settlement bucket; P&L-to-cash coupling is not claimed.
    At a 2k budget, KYC invariants prove on 22 states; the coupled checks cap.
  - ✅ M5 partners (2026-10-10), `benchmarks/broker/m5.py`: ten entities,
    105 actions, 72 scenarios; explicit restriction/capability matrix, tier
    changes, fresh-code consumption and withdrawals from a separate accrued
    wallet after irreversible blocking. Security-code coupling enlarges the
    cones; KYC invariants still prove on 22-state slices, other checks cap at 2k.
  - ✅ M6, `benchmarks/broker/m6.py`: 12 entities, 129 actions, 86 scenarios
    and two flows. Two concurrent risk accounts/orders/payment methods;
    worst-order/partial-stop probes and owned/currency-matched payment rails.
    M3 cash, risk equity, commissions and method settlement remain separate
    abstractions; all-balance termination and multiple M3 cash ledgers are not
    modelled. Tests pin those declared capacities and exercise a planted missing
    liquidation-priority guard.
  - ✅ Harness: `scripts/bench_broker.py`, equal budget override for every
    check, per-property cone/status/state/timing records and optional separate
    tracemalloc run. `benchmarks/broker/results-10000.json` stores full data and
    model/engine digests. All composed runs are INCONCLUSIVE. Slicing proves
    four KYC invariants on 22 states; whole-model checks prove none before the
    cap. At 10k the initial medians are ~6.1–6.5 s sliced / 2.0–2.4 s whole:
    multiple large cones cost more, while providing additional definitive results.
    Peak traced allocations at 10k are ~291/70 MiB (M4), 329/73 (M5), 391/91
    (M6), sliced/whole. Retained capped graphs and state storage now have a
    measured memory trigger for R4 profiling, without implying a complete proof.
- ✅ **C. Cone-of-influence slicing** per property, default for `check`
  (`validator/slicing.py`): exact, gated against the monolithic path on every
  example, plus 7 planted-defect probes (one per closure rule); superset
  reuse keeps coupled specs at parity; `--no-slice`. Issue-#3 shape: n=20
  independent lifecycles (~10¹⁸ states) all PASS in 0.02 s (research/34 §8)
- ✅ **D. Quint port of M1–M3** (`examples/broker/broker.qnt`): TLC distinct
  states identical at every increment (132 / 1,770 / 15,912); same verdicts and
  witness lengths. TLC core 1.2 s vs a full analint `check` of 2.7 s, but ~6 s
  wall (JVM). Apalache bounded is impractical at diameter 29, and its
  inductive proof needs an encoding rewrite. No NoDeadEnd / DeadActions in
  Quint. Quint is ~1.85× more compact (research/34 §8 D)
- ✅ `analint trace` for failing invariants (2026-10-09): canonical whole-model
  counterexamples with state diffs, shared invariant evaluation, initial/multi-root
  and evaluation-error witnesses; CLI + MCP. Query trace JSON stays unchanged;
  invariant payloads use `invariant` instead of `query` in `analint.trace/v1`.
  ✅ (2026-10-10) traces replay `check`'s decision (slices, budgets, invariant
  trust), so a witness found on a slice is traceable when the whole model is
  capped; `--no-slice` keeps the whole-model trace.
- ✅ **D for M4/M6 risk** (2026-10-10, `benchmarks/broker/risk.qnt`): the
  risk increment alone has identical distinct-state counts in analint and TLC
  (54,084 at M4 capacity; M6 capacity in research/34 §8 B2), same planted
  counterexample. Full M4 in TLC: 286,428,912 states, all 13 invariants hold
  (2 h 16 min); analint caps at 1M (research/34 §8 B2)
- ✅ **D for M5/M6** (2026-10-10, `benchmarks/broker/{partners,methods,m56}.qnt`):
  the partner and payment-method increments alone (576 / 1,766 states) and
  coupled with the client profile (12,672 / 38,852) have identical
  distinct-state counts, witnesses and planted counterexamples in analint and
  TLC; pinned by tests. Full M5/M6 are in Quint too (random simulation
  only). Finding: the shared one-time security code couples every process
  in a slice (research/34 §8 D for M5/M6)
- ✅ **Slicing refinement 3: disable-only writers** (2026-10-10): writers that
  only switch a flag off (a spent one-time code, a closed profile) no longer
  join slices through it; exact (research/34 §5), five planted probes, with a
  mutation per condition. Full M6 at 100k/check: 13 of 17 invariants proven
  (was 4); partner rewards on 192 states, payment methods on 38,852 (the
  TLC-checked coupling). Two latent slice-cache bugs fixed on the way (cache
  key and superset reuse ignored the action set)
- **E. Decision synthesis:** analint alone / compact state store / Quint export
  backend / partial-order reduction — chosen from B2+D measurements
  - ✅ Input (2026-10-10): per-state memory profile; state keys compacted to
    values + layout id (7.5 → 1.7 KB/state on M4, RSS 559 → 151 MiB at 50k,
    ~18% faster, graphs identical). Not the R4 store; research/34 §8 E
  - ✅ Input (2026-10-10): compiled guards/invariants and kernel trimming,
    ~1.8× end to end, differential-tested against the interpreter
  - ✅ **Exploration cache** (2026-10-12, `check --cache`): explore() memoised
    on disk by a canonical digest of its slice, roots, budget and the engine
    source; graphs are stored as value tuples, portable across processes.
    Reports equal a fresh run's (differential on every example, capped and
    uncapped, in process and across processes; digest probes and decoder
    mutations). Warm `check` on the broker: 0.6–1.0 s instead of 2.7–5.3 s; a
    `--what-if` hypothesis on a warm cache: 2.7 → 0.7 s
  - ✅ Incremental successor generation (2026-10-12): inherited rejections
    and invariant re-checks limited to written variables; byte-identical
    graphs, differential test plus presence mutation probes, `check`
    1.2–1.55× faster on the broker (research/36 §2.2)
  - Synthesis of the measured inputs: research/36 §1–§3
  - ✅ **Decision (2026-10-11, research/36 §4; accepted 2026-10-12):** layered. By default,
    analint with slicing and R4. `--tlc` (R6) is opt-in for cones beyond the
    in-memory budget. R5 POR is deferred, with a measured trigger.
    Product-sized cones are first a modelling question. Acceptance:
    run `check` with and without `--tlc` on the private spec and apply the
    §4 rule
  - ✅ **Acceptance (2026-10-12), branch 1 of the §4 rule:** on the private
    spec (8 entities, 64 actions), `check` ran 63.3 s → 7.6 s. Invariants
    went 0/5 → 5/5 PASS (slices of 45–51 actions, 272–1,360 states) and
    queries 4/7 → 6/7 PASS. `--tlc` had nothing to decide. One DeadActions
    action stays INCONCLUSIVE within the budget. That is a budget or model
    question for that spec (`--max-states`), not an engine gap
  - ✅ **R4 compact state store** (2026-10-10): a state is its key (one 16-bit
    code per entity slot, value tuples interned per layout slot); contexts
    are rebuilt from keys on demand, parents/edges are integer arrays. Memory
    is 8–15× lower per explored state (M4 risk 3,784 → 255 B, broker M3
    1,624 → 204 B). Full M4: 300k states 809 → 263 MiB at equal speed; 2M
    states / 11.5M edges in 1.13 GiB (1M needed 2.6 GiB before). `check` is
    4–7% slower (states decoded for scans). Graphs identical
    (characterization unchanged); codec round-trip and >16-bit escape tests
    (research/36 §2.5)
  - ✅ **R6 export to TLC** (2026-10-11): `check --tlc` (MCP `tlc`) decides
    invariants and Reachable/Unreachable/AlwaysHolds queries that the budget left
    INCONCLUSIVE. Each is exported on its own slice to TLA+, generated from the
    model (presence, terminal lock, simultaneous effects, bounds, lifecycle
    edges, invariant/inert-root pruning; kernel defects as `NoDefect_*`), and
    checked by TLC. What cannot be mirrored is refused, never approximated.
    TLC-gated tests pin equal state counts on every example and slice, and verdicts
    and traces equal to full-budget analint. Mutating any kernel rule out of the
    generator fails a test. It decides the open M4-risk and M6-profile queries in
    seconds. The full M4 risk cone still exceeds 30 min per check
    (research/36 §2.6). NoDeadEnd/DeadActions are not exported
  - **Checkpoint (2026-10-30):** P5 is accepted and complete, including the
    decision, compact storage, TLC, incremental exploration and disk caching.
    Continue with the current priorities at the top of this file. The original
    2026-10-10 M4–M6 handoff is superseded; do not repeat the completed benchmark,
    backend comparison or synthesis work.

### Далёкое будущее — явный IR и Rust-ядро — ⏸ ОТЛОЖЕНО (13 июня 2026)

Понижено разворотом от 13 июня 2026 (research/17 §3): обоснования IR были
«независимость от Python / мост к коду / Rust» — два из трёх сняты; соундность
(неизвестный AST-узел — ошибка) уже обеспечена без IR. Эмпирический потолок
~10⁵ состояний (research/17 §1.1) ещё не достигнут на реальных моделях —
оптимизировать нечего. Условия возврата наверх — research/17 §3 («Как откатиться»).

Замороженный план:

- сначала различить internal normalized semantic model, backend-specific
  execution plan, exploration result artifact и внешний wire format
- второй in-process backend не требует публичного JSON; внешний JSON-IR
  появляется только с реальным external consumer/second frontend/remote cache
- движок принимает не произвольные Python-объекты, а закрытую нормализованную
  модель; Python-DSL компилируется в неё одним модулем
- затем, только при подтверждённой необходимости, native backend: PyO3 может
  читать внутреннюю модель, отдельный бинарь потребует версионированный wire
  format; поверхность не меняется — люди и агенты пишут Python
- прецеденты «Python-фасад, Rust-ядро»: ruff, pydantic-core, polars.

Numba не является отдельным roadmap item: текущий object-heavy explorer для
него не подходит. После профиля реальной модели и lowering в integer
slots/opcodes сравнить optimized Python, Numba, Rust и другие варианты.
Сначала нужны algorithmic fixes/reductions; ускорение не устраняет
экспоненциальный state explosion (research/19).

---

## Принципы (выжимка из research/)

1. **Сначала движок умеет проверять — потом язык умеет выражать.** Новые
   примитивы без новых гарантий увеличивают «сложновато» впустую.
2. **Декларативность без исключений:** эффекты — факты о следующем состоянии,
   не команды; «выполнение» — интерпретация движком.
3. **JSON и стабильные id везде** — агент такой же first-class пользователь,
   как человек.
4. **Не публиковать до стабилизации имён** (v0.9), не оптимизировать до
   появления больших моделей (Rust — после спроса).

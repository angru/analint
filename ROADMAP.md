# analint — Roadmap

Текущее состояние: **v1.0.1 + v1.2 expressiveness** — универсальный DSL +
агентская поверхность +
reachability-движок (Reachable/Unreachable/AlwaysHolds/NoDeadEnd/DeadActions,
Field-границы, трассы-контрпримеры), Param, arithmetic AST, multi-root,
bounded multiplicity, конечные `ForAll/Exists`, `Count/Sum/Min/Max`,
declarative initial relations, presence semantics и `Create/Delete` в
фиксированном universe, явные `Contract` и композиция спек, единый transition
kernel (`validator/kernel.py`), canonical model с `Spec.initial` и
авто-верификацией инвариантов, исполняемые `Flow`. 291 тест; первая внешняя
evidence-модель (GitHub branch protection, research/23). Фазы v0.9,
v0.10 и v1.0
ниже выполнены.
Из v1.0 отложено: реляционные эффекты f.next и `analint simulate` — по спросу.

**Этот файл — единственный источник истины по статусу и приоритетам.**
Документы `research/*` — датированные обоснования, на которые он ссылается;
приоритеты, живущие только в research, считаются устаревшими. История смены
приоритетов (что было → что стало → когда → почему → как откатиться) —
в research/17 §3; критический аудит и errata — research/18.

Этот роадмап выведен из исследования в `research/` (файлы 00–19). Краткая
логика: ядро DSL удачное (≈ планировочный домен STRIPS), узкие места —
многословность поверхности, отсутствие движка поиска по состояниям и
отсутствие интерфейса для AI-агентов, которые признаны главным сценарием
(research/08).

---

## Текущие приоритеты (уточнено 13 июня 2026)

После закрытия всей дорожки выразительности (v1.2+) и эмпирического аудита
движка (research/17 §1) фокус смещён с «связать спеку с реализацией» на
**полноту и надёжность движка как инструмента, которым просто описать систему и
проверить её согласованность — без привязки к реализации**. Второй аудит
(research/18) обнаружил более срочные false-green и уточнил порядок.

Топ-приоритеты (фаза v1.3 ниже):

1. **Закрыть false-green:** ✅ `INCONCLUSIVE` не является PASS (трёхзначный
   `verdict`, JSON `passed`=PASS-only, exit-код 4); ✅ explorer проверяет
   `Action.post`, включая effectless actions (review 584d819 P1).
2. ✅ **Единая transition semantics** — `validator/kernel.py` `step()` для
   scenario, explorer и будущего Flow (закрыты explorer-`post`, lifecycle-переход
   в scenario, `Delete` в terminal guard, emitted payload, pre-state invariant).
3. ✅ **Canonical `Spec.initial`** + автоматическая проверка invariants по
   reachable states (секция `InvariantResult`; статус проверки четырёхзначен,
   общий verdict трёхзначен; NOT_CHECKED/INCONCLUSIVE вместо silent pass).
4. ✅ **Исполняемый многошаговый trace** — `Flow` с `given` + смешанными
   checkpoints через общий kernel, без рукописных state deltas (artifact —
   follow-up).
5. **Семантическая честность `by/on/requires/emits`**: поведение или явно metadata.
6. **Внешние реальные модели** как gate для дальнейшего расширения языка.

Сознательно отложено (с обоснованием и условиями отката — research/17 §3):
явный IR, тяжёлый мост к коду (pin/якоря/adapter), отдельная команда
`analint diff`, Rust-ядро.

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
- ⏸ отдельные CLI `analint query` / `analint trace` не реализованы
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

### v1.3 — Семантическое ядро (активная фаза, с 13 июня 2026)

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
  трассой. Flow без `given` остаётся документацией. `FlowResult` влит в verdict,
  warning-агрегацию, terminal/JSON репортеры и characterization; `validator/flow_runner`
- ✅ post-state шага становится pre-state следующего через общий transition kernel
- ✅ «слои» как arbitrary snapshot deltas НЕ добавлены: только реальные действия
  через kernel (preconditions всегда соблюдены)
- ⏳ exploration result artifact (roots/nodes/edges/findings/traces, completeness,
  summary) как основа CLI/MCP/визуализации — отдельный follow-up, не model IR

#### P3. Семантическая честность словаря

Решено (reviews/8cca900): honesty-pass, БЕЗ новой семантики. `by`/`on`/`requires`
— явно documentary metadata; операционный `on` отложен за evidence-gate
(research/22 §«Разворот»: мультимножество-пул не ограничен конечным payload;
consume меняет смысл `Event`; ломает state-chaining саги; нет внешних моделей).

- ✅ `Actor/by`: documentary metadata (не authz), зафиксировано в docstring
  Action и README. `by` не расширять до списка до решения principal-семантики
- ✅ `Event/emits/on`: `emits` — поведение (материализация payload + `Emitted`);
  `on` — documentary (не trigger; причинность через состояние). Формулировки
  без «triggers/subscribe» во ВСЕХ поверхностях: docstrings Action/Event, README,
  structural warning, **и agent-facing API** — `affects` JSON отдаёт
  `documented_handlers` (был `triggers_downstream`), MCP-описание переформулировано
  (закрыто ревью 4465e16)
- ✅ `requires`: явно Flow-ordering documentation (cycles + порядок), не
  операционный prerequisite; зафиксировано в docstring/README
- ⏳ предупреждение о потенциально безграничных числовых доменах — после общего
  inconclusive verdict
- ⏳ операционный `on` (event dispatch) — только при подтверждении внешним
  evidence-кейсом, что state-протокола недостаточно (research/22 пункты 1–5)

#### Evidence gate (параллельно с P0, блокирует новые примитивы)

- ⏳ две модели существующих систем, не придуманных под analint — **1 из 2**:
  ✅ `examples/branch_protection` (GitHub protected PR policy, research/23, с
  source/assumption matrix и fidelity-фиксами после ревью 4465e16);
  ⏳ вторая — должна нагружать composition + несколько экземпляров, а не повторять
  сильную сторону текущего движка (single-entity policy)
- ⏳ один и тот же case в analint и Quint или FizzBee — пока структурное
  сравнение (research/23), не полный порт. Порт особенно важен для path/temporal
  свойств, которые analint (только reachability) выразить не может
- ✅ a series of four requirement changes is measured (research/23 "Change
  series"): dismiss-stale off, strict→loose checks, require-approval-of-latest-push,
  allow-bypass — each with its saved diff, state-count delta and blast radius. Two
  are local few-line edits; change 3 hits the identity boundary (×3.6 states,
  reviewer identity required); change 4 detonates every global guarantee until
  re-scoped. The reachability-only ceiling (can't see "stale"/history) is now shown
  by a change, not just asserted
- ✅ первый внешний change-oriented candidate реализован: GitHub protected
  pull-request policy (approvals, stale reviews, status checks, code owners).
  В **этой абстракции** (одна агрегированная PR-политика) события не
  понадобились — не опровергает разворот research/22; demand на event pool не
  обнаружен (но multi-PR/merge-queue/async не покрыты — задача для второй модели)
- event pool, time/concurrency primitives, Computed и domain profiles — только
  по результатам этих моделей
- если change workflow не лучше Quint/FizzBee, рассмотреть analint как domain
  frontend/analysis layer над существующим verifier вместо расширения своего

### Параллельная дорожка — экосистема

- **После v0.9** (имена стабильны): публикация на GitHub, PyPI, лицензия,
  CONTRIBUTING, CI самого analint
- Документация-сайт (mkdocs) после v0.10 — когда есть что показывать агентам
- После P0/P1: CLI-first diagnostics из exploration artifact — state diff traces,
  statistics, Mermaid/DOT для Lifecycle/action dependencies
- Interactive explorer (enabled/disabled actions, fork/rewind, failed guards) —
  после executable traces; полный state graph только для малых/агрегированных моделей
- Performance: parameterized synthetic families (counter grid, conserved
  transfers, workflow product) с 10²–10⁵ states; timing не CI gate. Текущие
  examples (максимум 216 states) остаются smoke, не scaling benchmark

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

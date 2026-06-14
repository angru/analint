# Review: executable Flow after 02488cd..2015619

Дата ревью: 14 июня 2026.

Коммиты:

```text
673dfe2 Make Flow executable: multi-step traces through the kernel
2015619 Mark P2 executable trace done in the roadmap
```

## Verdict

Направление правильное: post-state действительно передаётся следующему action
через общий kernel, arbitrary state deltas не появились, FlowResult включён в
общий fail-closed verdict и reporters.

Отказ от общего базового `Step` сейчас также правильный. У него нет собственной
семантики, поэтому wrapper только увеличил бы DSL. Но P2 рано объявлять
полностью закрытым: executable Flow имеет три подтверждённых false-green.

Статус:

> Mixed `Action | Assert | Emitted` оставить. Flow runner требует hardening до
> перехода к следующему semantic primitive.

## Findings

### P1. Flow не проверяет world invariants

Файлы:

- `src/analint/validator/flow_runner.py:22`
- `src/analint/validator/kernel.py:1`
- `src/analint/validator/scenario_runner.py:29`
- `ROADMAP.md:287`

`kernel.step()` намеренно проверяет transition, но не законность world state.
Scenario добавляет invariant checks до и после шага, explorer проверяет roots и
successors. Новый `run_flow()` этого не делает.

Поэтому Flow может успешно пройти через состояние, нарушающее invariant, даже
когда canonical verification остаётся зелёной:

```python
class Counter(Entity):
    n: int = 0

break_it = Action(
    id="break",
    pre=[Counter.n == 1],
    effect=[Set(Counter.n, -1)],
)

flow = Flow(
    id="f",
    given=[Counter(n=1)],
    steps=[break_it],
)

spec = Spec(
    ...,
    invariants=[Invariant(Counter.n >= 0, id="non_negative")],
)
```

Фактический результат probe:

```text
flow: PASS
flow findings: []
canonical invariant: PASS
```

Canonical root имеет `n=0`, поэтому action там disabled; нарушение существует
только на конкретном journey snapshot и нигде больше не ловится.

Нужно проверять применимые invariants:

1. на initial Flow context до первого action;
2. на каждом принятом post-state до продолжения journey.

Логику лучше вынести из `scenario_runner` в общий state-check helper, а не
копировать третий раз. Initial invariant violation и post invariant violation
должны быть model defects и валить Flow с trace.

### P1. Незарегистрированный Action проходит по совпадающему `id` и исполняется

Файлы:

- `src/analint/validator/structural.py:446`
- `src/analint/validator/flow_runner.py:44`

Structural validation обещает, что action step зарегистрирован, но сравнивает
только `step.id`. Runner затем исполняет сам объект из `flow.steps`.

```python
registered = Action(id="same", effect=[Set(Box.n, 1)])
foreign = Action(id="same", effect=[Set(Box.n, 2)])

flow = Flow(
    given=[Box()],
    steps=[foreign, Assert(Box.n == 2)],
)
spec = Spec(actions=[registered], flows=[flow], ...)
```

Фактический результат:

```text
structural errors: none
flow: PASS
```

Это нарушает explicit composition contract: содержимое Flow может исполнять
transition, отсутствующий в `spec.actions`.

Проверка должна быть по object identity (`id(obj)` / `is`), как и collection
dedup в проекте. Совпадение `id` пригодно для diagnostics, но не доказывает
регистрацию объекта. Добавить regression с двумя Action одного id и разными
effects.

Тот же паттерн стоит отдельно проверить для `Scenario.action` и
`Action.requires`: там сейчас также используется id-based membership.

### P1. `Emitted` даёт false PASS для другого Event-класса с тем же именем

Файлы:

- `src/analint/validator/flow_runner.py:70`
- `src/analint/validator/structural.py:473`
- `src/analint/validator/scenario_runner.py:102`
- `src/analint/validator/structural.py:194`

Runner сводит emitted events к `__name__`, а structural validation проверяет
только то, что checkpoint содержит subclass `Event`. Регистрация checkpoint
event в `spec.events` не проверяется.

Два разных класса с `__name__ == "Signal"` дают:

```text
registered action emits RegisteredSignal
flow checks Emitted(ForeignSignal)
structural errors: none
flow: PASS
```

Checkpoint утверждает identity типа, поэтому сравнение должно использовать
точный class object:

```python
seen = {event if isinstance(event, type) else type(event) for event in emitted}
if entry.event_cls not in seen:
    ...
```

Structural validation должна требовать `entry.event_cls in spec.events`.
Исправление следует применить и к Scenario, action `emits/on` и handled-event
matching: существующая name-based policy имеет тот же identity blind spot.

### P2. `given=[]` одновременно означает documentation и валидный empty/default initial

Файлы:

- `src/analint/models/flow.py:37`
- `src/analint/validator/engine.py:96`

Executable mode определяется через truthiness `flow.given`. Из-за этого нельзя
выразить исполняемый Flow, который стартует из defaults-built world: пустой
`given` всегда превращает его в документацию.

Это не связано со Step abstraction. Здесь смешаны два независимых признака:

- есть ли у Flow execution mode;
- сколько explicit snapshots нужно initial state.

Минимальный явный контракт:

```python
given: list[Any] | None = None
```

где `None` означает documentary Flow, а `[]` — executable Flow с initial,
построенным из defaults. Другой вариант — отдельное поле `initial`, совместимое
с canonical initial builder. Не стоит использовать непустоту данных как mode
switch.

Параллельно стоит решить, допустим ли executable Flow без единого Action:
сейчас `given=[...]`, `steps=[]` даёт PASS и считается успешным flow.

### P2. Public README всё ещё утверждает, что Flow не исполняется

Файл:

- `README.md:433`

README говорит:

```text
Flow is currently structural documentation; the linter does not execute state.
```

Это прямо противоречит новой реализации и ROADMAP. Пользователь, следующий
основной документации, не узнает о `given`, checkpoints, failure semantics и
том, что Flow влияет на общий verdict.

README и `AGENTS.md` следует обновить в том же commit, который объявляет P2
выполненным.

### P2. `steps_run` считает actions, а reporter называет их всеми steps

Файлы:

- `src/analint/validator/flow_runner.py:39`
- `src/analint/reporter/base.py:87`
- `src/analint/reporter/terminal.py:102`

Для Flow из пяти entries:

```python
[action, Assert(...), action, Assert(...), Emitted(...)]
```

JSON и terminal показывают `2 steps run`. Фактически это число выполненных
actions; checkpoints в счётчик не входят.

Нужно либо переименовать поле в `actions_run`, либо считать обработанные entries
и отдельно хранить action trace. Сейчас публичный result artifact двусмыслен.

## Решение по `Step`

### Отдельный базовый `Step` сейчас не нужен

Текущий Flow уже является простой алгеброй:

```text
FlowEntry = Action | Assert | Emitted
Flow = sequence[FlowEntry]
```

Общий `Step(action=...)` не добавит:

- новой проверки;
- нового state transition;
- новой композиции;
- новой информации для runner.

Он только заставит оборачивать каждое действие и увеличит authoring surface.
Три найденных false-green он также не исправляет.

### Но `list[Any]` слишком слаб

Отказ от base class не означает отказ от закрытого grammar. При Python 3.14
можно объявить:

```python
type FlowEntry = Action | Assert | Emitted

@dataclass
class Flow:
    steps: list[FlowEntry] = dc_field(default_factory=list)
```

Structural validation всё равно нужна для runtime-loaded DSL, но type alias
улучшит IDE/type-checking и явно зафиксирует допустимые узлы.

### Когда отдельный invocation node станет оправдан

Не общий абстрактный `Step`, а узкий action-occurrence node может понадобиться,
если конкретное вхождение action должно нести данные, которых нет в декларации:

- event payload для action с operational `on`;
- principal/actor binding после определения semantics `by`;
- ожидаемый rejection конкретного шага;
- label/source metadata для trace;
- per-occurrence timeout/retry policy, если такие semantics вообще появятся.

До появления хотя бы одного реального требования bare Action лучше сохранить.
Не следует вводить generic `Step` заранее ради гипотетических branches,
parallelism или UI.

`Emitted` semantics также нужно зафиксировать: сейчас checkpoint означает
«event был emitted когда-либо ранее в этом Flow», а не «предыдущим action».
Это допустимый выбор, но он должен быть явно описан и протестирован повторными
event checkpoints.

## Что сделано хорошо

- Flow использует общий transition kernel, а не второй effect evaluator.
- Post-state действительно становится pre-state следующего action.
- REJECTED и DEFECT оба fail-closed для journey.
- Arbitrary snapshot deltas не добавлены.
- Checkpoints можно ставить между любыми actions.
- FlowResult включён в overall verdict, JSON, terminal и characterization.
- Documentary Flow сохранён как режим миграции для существующих specs.
- Taskboard даёт реальный multi-step example, а не только unit fixture.

## Проверка

```text
.venv/bin/pytest -q              281 passed, 1 skipped
.venv/bin/ruff check .           passed
.venv/bin/ruff format --check .  passed
.venv/bin/ty check               passed
git diff --check                 passed
```

Зелёные examples:

```text
ecommerce
taskboard
cloak
mafia
fulfillment
sunless_crypt
```

Targeted probes подтвердили:

```text
invariant-violating Flow                         -> PASS
foreign Action with registered id                -> PASS
foreign Event class with registered class name   -> PASS
empty executable Flow                            -> PASS
```

## Рекомендуемый следующий commit

1. Добавить invariant checks initial/post для Flow.
2. Перевести action/event registration и emitted checks на object identity.
3. Разделить documentary mode и empty/default executable initial.
4. Исправить README/AGENTS и `steps_run` naming.
5. Заменить `list[Any]` на закрытый `FlowEntry` union без введения base `Step`.

После этого P2 executable trace можно считать закрытым и переходить к
семантическому аудиту `by/on/requires/emits`.

---

## Resolution

Закрыто коммитом `84caa3f` (14 июня 2026). Все три false-green воспроизведены
пробами до фикса:

- **P1 (invariants)** — `run_flow` проверяет применимые invariants на initial
  context и после каждого принятого action; нарушение → flow FAIL с trace.
  Логика вынесена в `validator/state_checks` (`relevant_invariants` +
  `check_invariants`) и переиспользуется scenario_runner и flow_runner (третьей
  копии нет).
- **P1 (action identity)** — structural проверяет шаг по `id(obj)` против
  `{id(a) for a in spec.actions}`; foreign Action с тем же id строки —
  structural ERROR.
- **P1 (event identity)** — `Emitted` сравнивает точный class object; structural
  требует `event_cls in spec.events`. Два класса с именем "Signal" больше не
  удовлетворяют друг друга.
- **P2 (given)** — `Flow.given: list | None`; `None` = документация, список
  (в т.ч. `[]`) = executable (initial из snapshots + default-constructible
  entities). Mode больше не зависит от truthiness данных. Executable flow без
  actions → structural WARNING.
- **P2 (README/AGENTS)** — обновлены: Flow исполняется (given + checkpoints +
  failure semantics + влияние на verdict).
- **P2 (steps_run)** — переименовано в `actions_run` (считает actions, не
  checkpoints) в result/reporters/snapshot.

По `Step`: оставлен mixed `Action | Assert | Emitted` без base-класса (как
рекомендовано). Закрытый `FlowEntry`-union на поле НЕ введён сознательно:
`steps` остаётся `list[Any]`, потому что Flow интроспектируется pydantic (через
`Spec.flows`), и конкретный union заставил бы pydantic ревалидировать/копировать
step-объекты, ломая identity-проверку action-шага. Грамматика закрыта structural
validation. `Emitted` semantics («эмитнуто к этому моменту») зафиксирована в
docstring и покрыта тестом.

Проверка: `uv run pytest` — 286 passed, 1 skipped; `ruff check`, `ruff format
--check`, `ty check` зелёные.

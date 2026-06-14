# Review: Flow hardening after 2015619

Дата ревью: 14 июня 2026.

Коммиты:

```text
84caa3f Harden executable Flow (review 2015619)
218f250 Record resolution of the executable-flow review
c7b7686 Refresh roadmap test count after flow hardening (286)
```

## Verdict

Предыдущие три Flow probes закрыты:

- обычный post-state invariant violation теперь валит Flow;
- foreign Action с совпадающим id даёт structural ERROR;
- Flow `Emitted` сравнивает Event classes по identity;
- `given=[]` запускает Flow, `given=None` оставляет документацию;
- `actions_run`, README и AGENTS приведены в соответствие.

Но hardening пока неполный. Новый invariant helper неверно учитывает presence,
а identity policy применена только к Flow, хотя те же false-green остались в
Scenario и Action metadata. P2 executable trace лучше не считать полностью
закрытым до первого исправления.

## Findings

### P1. Invariant applicability ломается на `Create/Delete` внутри Flow

Файлы:

- `src/analint/validator/state_checks.py:19`
- `src/analint/validator/flow_runner.py:44`
- `src/analint/validator/flow_runner.py:63`

`relevant_invariants()` считает invariant применимым, если context содержит его
key. Но bounded Scope хранит `Absent(ref)` под тем же key, поэтому наличие key
не означает наличие entity.

Кроме того, Flow вычисляет список `relevant` один раз на initial context и
переиспользует его после всех actions. Для presence semantics применимость
может меняться после каждого `Create`/`Delete`.

Probe:

```python
class Account(Entity):
    balance: int = 0

accounts = Scope(Account, keys=["eve"])
eve = accounts["eve"]

open_eve = Action(
    id="open",
    effect=[Create(eve, balance=0)],
)

flow = Flow(
    id="f",
    given=[Absent(eve)],
    steps=[open_eve],
)

spec = Spec(
    ...,
    invariants=[Invariant(eve.balance >= 0, id="non_negative")],
)
```

Фактический результат:

```text
flow: FAIL before the action
invariant: evaluation error: Entity 'Account["eve"]' is absent
```

По существующему контракту invariant, entity которого отсутствует, должен быть
неприменим в этом state. После `Create` тот же invariant обязан стать применим.
После `Delete` — снова неприменим.

Нужен один state-level helper вида:

```python
check_applicable_invariants(spec, context, label)
```

который на каждом state:

1. заново собирает refs;
2. проверяет наличие context key;
3. для `InstanceRef` проверяет `is_present(context, ref)`;
4. только затем вычисляет invariant.

Его следует использовать в Scenario, Flow и explorer/canonical verification.
Сейчас `state_checks` общий только для Scenario/Flow, а explorer сохраняет
отдельную реализацию с тем же key-only blind spot.

Добавить regressions для:

- absent → `Create` → invariant checked;
- present → `Delete` → invariant skipped;
- invalid value, созданное через `Create`, → Flow FAIL.

### P1. Scenario всё ещё исполняет незарегистрированный Action по совпадающему id

Файлы:

- `src/analint/validator/structural.py:72`
- `src/analint/validator/structural.py:330`
- `src/analint/validator/scenario_runner.py:32`

Flow membership переведён на identity, но Scenario остаётся id-based:

```python
registered = Action(id="same", effect=[Set(Box.n, 1)])
foreign = Action(id="same", effect=[Set(Box.n, 2)])

scenario = Scenario(
    action=foreign,
    given=[Box()],
    then=[Assert(Box.n == 2)],
)

spec = Spec(actions=[registered], scenarios=[scenario], ...)
```

Фактический результат:

```text
structural errors: none
scenario: PASS
```

Это тот же explicit-composition false-green, который исправлен для Flow.
Любой executable reference должен быть зарегистрирован по object identity.

Нужно применить одну membership policy к:

- `Scenario.action`;
- `Flow` Action entries;
- `Action.requires`.

Для `requires` совпадение id сейчас также считается регистрацией и порядком,
хотя объект может быть foreign copy.

### P1. Event identity исправлена только для Flow checkpoint

Файлы:

- `src/analint/validator/scenario_runner.py:92`
- `src/analint/validator/structural.py:162`
- `src/analint/validator/structural.py:194`
- `src/analint/validator/structural.py:220`

Flow `Emitted` теперь корректно использует class identity. Но остальные пути
по-прежнему сводят Event к `__name__`:

- Scenario `Emitted`;
- registration `Action.emits`;
- registration `Action.on`;
- matching emitted/handled events.

Два разных класса с `__name__ == "Signal"` подтверждают:

```text
Scenario Emitted(ForeignSignal): PASS
Action emits ForeignSignal while spec.events=[RegisteredSignal]:
  no structural ERROR
Action on=[ForeignSignal] while spec.events=[RegisteredSignal]:
  no structural ERROR
```

Это особенно опасно после composition/contracts, где class identity является
частью модели. Нужен единый identity-based event registry:

```python
registered_events = set(spec.events)
handled_events = {event_cls ...}
```

И exact class comparison во всех runtime checkpoints.

### P2. Обоснование сохранения `steps: list[Any]` не подтверждается

Файл:

- `src/analint/models/flow.py:44`

Resolution утверждает, что union annotation заставит Pydantic
ревалидировать/копировать step objects и сломает identity. Probe с тем же
контуром — dataclass Flow внутри Pydantic BaseModel с
`list[Action | Assert]` — показал:

```text
flow object identity preserved:   True
Action object identity preserved: True
Assert object identity preserved: True
```

Текущий `Spec(flows=[flow])` также сохраняет все identities.

То есть отказ от base `Step` по-прежнему правилен, но `Any` не требуется.
Следует добавить реальный model regression и использовать:

```python
type FlowEntry = Action | Assert | Emitted
steps: list[FlowEntry]
```

Если существует другой input path, на котором Pydantic создаёт копии, его
нужно воспроизвести тестом и исправить явно. Комментарий в production code не
должен фиксировать неподтверждённое ограничение.

### P2. `given=[]` имеет другую default semantics, чем canonical initial

Файлы:

- `src/analint/validator/flow_runner.py:99`
- `src/analint/validator/explorer.py:153`

Для non-scoped entities Flow действительно вызывает default constructor. Для
Scope slots он всегда создаёт `Absent(ref)`. Canonical `build_initial(spec, [])`
делает обратное: default-constructible Scope refs создаются present.

Probe:

```text
canonical initial:
  Account["alice"] present, balance=0

Flow(given=[]):
  Account["alice"] absent
  Set(Account["alice"].balance, 1) -> REJECTED
```

Поэтому формулировка «empty given = defaults-built world» неоднозначна, а
Flow/query с одинаковым пустым initial стартуют из разных миров.

Нужно выбрать и зафиксировать один контракт:

1. `given=[]` использует общий `build_initial` и совпадает с canonical model;
2. либо Flow использует scenario-style partial snapshot, где unspecified Scope
   slots absent, но это нужно явно назвать и не описывать как canonical/default
   initial.

Предпочтительнее не держать третий initial builder. Flow может принимать общий
`Initial`/initial-source abstraction либо переиспользовать существующий helper.

## Что исправлено хорошо

- Обычные invariants проверяются на initial и post-state Flow.
- State check вынесен из Scenario runner, а не скопирован.
- Flow Action membership использует identity.
- Flow `Emitted` runtime и structural checks используют class identity.
- Documentary/executable mode больше не зависит от truthiness списка.
- `actions_run` точно описывает публичный result field.
- README и AGENTS соответствуют executable Flow.
- Empty executable Flow явно получает structural warning.

## Проверка

```text
.venv/bin/pytest -q              286 passed, 1 skipped
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

Повторные probes прошлого review:

```text
ordinary invariant violation in Flow -> FAIL
foreign Flow Action with same id     -> structural ERROR
foreign Flow Event class             -> FAIL / structural ERROR
Flow(given=[]) with plain Entity      -> PASS
```

Новые probes:

```text
Absent scoped entity + invariant + Create -> false FAIL before Create
foreign Scenario Action with same id      -> PASS
foreign Scenario Event with same name     -> PASS
foreign emits/on Event with same name     -> no structural ERROR
typed FlowEntry union                     -> identities preserved
empty Flow vs canonical Scope defaults    -> different initial worlds
```

## Рекомендуемый следующий commit

1. Сделать invariant applicability presence-aware и пересчитывать на каждом state.
2. Завершить identity audit для Scenario, requires, emits и on.
3. Ввести typed `FlowEntry` union с regression на identity.
4. Унифицировать или явно развести Flow и canonical initial semantics.

После первых двух пунктов P2 executable trace можно считать корректностно
закрытым. Остальные два — API/модельный hardening перед P3.

---

## Resolution

Закрыто коммитом `da693d4` (14 июня 2026). Все пять находок воспроизведены
пробами до фикса (включая P2#4 — подтверждено, что pydantic сохраняет identity
с union-аннотацией, т.е. прежнее обоснование `list[Any]` было неверным).

- **P1 (presence)** — applicability стала presence-aware и пересчитывается на
  каждом state: `check_invariants(spec, context, label)` пропускает инвариант,
  чья entity отсутствует (Scope-слот хранит ключ при `Absent`). `Create` делает
  инвариант применимым, `Delete` — снова неприменимым. Общий helper в
  `state_checks` для scenario и flow; в explorer добавлен тот же guard.
  Regressions: absent→Create→checked, bad Create→FAIL.
- **P1 (action identity)** — членство executable-ссылки по `id(obj)` для
  `Scenario.action`, `Action.requires` и flow-шагов; foreign Action с тем же
  id строки → structural ERROR.
- **P1 (event identity)** — единые `registered_events`/`handled_events` (классы);
  Scenario `Emitted`, `emits`, `on` и matching сравнивают точный class. Два
  класса "Signal" больше не удовлетворяют друг друга.
- **P2 (FlowEntry)** — `steps: list[FlowEntry]` (`Action | Assert | Emitted`).
  Проба подтвердила сохранение identity step-объектов через `Spec(flows=[...])`;
  `list[Any]`-обоснование снято.
- **P2 (initial semantics)** — scenario и flow используют один
  `build_snapshot_context` (given + absent Scope-слоты). `given=[]` — явный
  partial snapshot, НЕ canonical defaults-world; docstring и README исправлены;
  non-scoped autofill убран.

По `Step`: оставлен mixed union без base-класса (как рекомендовано); `Emitted`
semantics («эмитнуто к этому моменту») зафиксирована в docstring и покрыта тестом.

Проверка: `uv run pytest` — 287 passed, 1 skipped; `ruff check`, `ruff format
--check`, `ty check` зелёные.

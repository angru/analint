# Review: identity/presence hardening and event-dispatch direction

Дата ревью: 15 июня 2026.

Коммиты:

```text
da693d4 Close the identity, presence and naming gaps (review c7b7686)
9792b7e Record resolution of the flow-hardening review
398004e Refresh roadmap test count after identity/presence hardening (287)
8cca900 Design event dispatch: operational on (research/22)
```

## Verdict

`da693d4` качественно закрывает почти все находки прошлого review:

- Scenario/Flow/requires membership проверяется по Action identity;
- Event identity используется в Scenario, `emits`, `on` и Flow;
- Flow получил закрытый `FlowEntry` union без base `Step`;
- Scenario и Flow используют один partial-snapshot builder;
- Flow invariant applicability пересчитывается после `Create/Delete`.

Но presence fix не доведён до canonical invariant result: после `Delete`
автоматическая проверка invariant всё ещё даёт ложный FAIL.

По следующему направлению verdict строже:

> `research/22` не следует реализовывать в текущем виде. Он превращает
> domain-shaped DSL в модель очереди сообщений, перескакивает evidence gate и
> оставляет незаданными boundedness, fan-out, scheduling и event selection.

Сначала нужно закрыть остаточный soundness bug и провести внешний evidence case.
Для P3 безопасный минимальный шаг сейчас — честно закрепить `on/by/requires` как
metadata, а не добавлять event pool.

## Code Findings

### P1. Canonical invariant verification всё ещё падает на absent state

Файлы:

- `src/analint/validator/explorer.py:643`
- `src/analint/validator/explorer.py:462`
- `src/analint/validator/state_checks.py:19`

Per-state explorer guard теперь presence-aware, но `_verify_one_invariant()`
имеет старую key-only проверку. После `Delete` absent slot остаётся в context,
поэтому функция пытается вычислить его поле и возвращает FAIL.

Probe:

```python
class Account(Entity):
    balance: int = 0

accounts = Scope(Account, keys=["eve"])
eve = accounts["eve"]

close = Action(id="close", effect=[Delete(eve)])
non_negative = Invariant(eve.balance >= 0, id="non_negative")
```

Фактический результат:

```text
states explored: 2
exploration findings: []
InvariantResult: FAIL
trace: ["close"]
finding: evaluation error: Entity Account["eve"] is absent
```

Это внутреннее противоречие одного run: exploration считает invariant
неприменимым, итоговый invariant scanner считает тот же state ошибкой.

Не нужно добавлять третий локальный guard. Следует вынести один helper:

```python
invariant_is_applicable(invariant, context)
```

и использовать его в:

- Scenario/Flow state checks;
- `_report_invariant_violations`;
- `_verify_one_invariant`.

Regression: present root → `Delete` → invariant над полем удалённого slot
остаётся PASS, если он держался во всех состояниях, где slot был present.

### P2. Presence applicability пока раздвоена между двумя реализациями

Файлы:

- `src/analint/validator/state_checks.py`
- `src/analint/validator/explorer.py`

Scenario/Flow используют `_applicable`, explorer вручную повторяет похожий
алгоритм. Уже сейчас они разошлись в `_verify_one_invariant`.

Presence semantics является частью общего state contract, а не runner detail.
Helper должен жить в одном месте и принимать predicate/invariant + context.
Иначе следующий state extension (event pool) умножит число таких расхождений.

## Event Dispatch Findings

### Blocker. Finite payload не делает multiset event pool конечным

Файл:

- `research/22-event-dispatch.md:28`

Документ утверждает, что BFS конечен при конечных payload domains. Это неверно
для мультимножества.

Даже единственное payloadless событие `Tick` создаёт бесконечное пространство,
если action может повторно emit без обязательного consume:

```text
{}
{Tick}
{Tick, Tick}
{Tick, Tick, Tick}
...
```

Конечный alphabet не ограничивает multiplicity. Нужен один из явных контрактов:

- bounded pool capacity;
- set semantics с дедупликацией;
- per-event multiplicity bound;
- synchronous delivery без хранения;
- либо честное признание, что почти любая повторная emission делает proof
  INCONCLUSIVE.

Без этого event pool нельзя считать bounded transition model.

### Blocker. Consume semantics не соответствует текущему понятию domain event

Файлы:

- `research/22-event-dispatch.md:13`
- `research/12-domain-layer-and-ddd.md:84`
- `README.md:357`

Текущие документы называют Event доменным сигналом и subscription. Consume
pool превращает его в queue message/job:

- одно событие обрабатывает ровно один handler;
- добавление второго handler меняет поведение первого;
- composition двух Contracts создаёт конкуренцию за один ресурс;
- audit/notification/projector subscribers не получают одно событие вместе.

Это не локальная implementation choice. Это публичная domain semantics.
`on=` читается как subscription/broadcast заметно естественнее, чем exclusive
consume.

Если нужен linear resource, честнее ввести отдельное понятие `Message` /
`consumes`, а `Event` оставить observable domain fact. Если новое имя пока не
оправдано evidence, не следует делать `on` operational.

### Blocker. Не определены trigger choice и action occurrence

Файл:

- `research/22-event-dispatch.md:17`

Не заданы ответы:

- `on=[A, B]` означает any-of или одновременное наличие обоих?
- если в pool несколько `A` с разными payload, какое выбирает Scenario/Flow?
- если action pre подходит только одному payload, другие остаются?
- может ли handler читать одновременно два event classes?
- является dispatch обязательным/автоматическим или просто ещё одним enabled
  action, который можно никогда не выбрать?

Explorer может ветвиться, но executable Flow содержит bare `Action`, без
event-occurrence binding. Именно здесь впервые появляется реальная причина для
узкого invocation node:

```python
Run(handler, event=...)
```

или другого явного input binding. Это не аргумент возвращать generic `Step`;
это аргумент сначала определить occurrence semantics.

### P1. Документ неверно фиксирует момент вычисления emitted payload

Файлы:

- `research/22-event-dispatch.md:15`
- `src/analint/validator/kernel.py:386`

Research говорит, что payload вычисляется против pre-state «как сейчас».
Текущий kernel явно вычисляет templates против `post`.

Например, после `Set(Order.status, PAID)`:

```python
emits=[OrderChanged(status=Order.status)]
```

сейчас получает `PAID`, а не предыдущее значение.

Нужно выбрать контракт осознанно. Для domain event «что произошло» post-state
часто естественнее; для event carrying old/new нужны явные expressions. Нельзя
строить pool implementation поверх неверного описания существующей семантики.

### P1. Bare Event class несовместим с operational payload

Файлы:

- `src/analint/models/action.py`
- `src/analint/validator/kernel.py:391`
- `research/22-event-dispatch.md`

API разрешает:

```python
class Required(Event):
    payload: str

Action(emits=[Required])
```

Structural validation не считает это ошибкой, а kernel пропускает сам class без
payload. В event pool handler с `pre=[Required.payload == ...]` не сможет
получить значение.

До operational dispatch нужно решить:

- bare class разрешён только для payloadless Event;
- либо required fields обязаны задаваться template instance;
- либо class emission получает отдельную token semantics.

### P2. Sentinel в entity context увеличивает связанность ядра

Файл:

- `research/22-event-dispatch.md:36`

Sentinel экономит изменение сигнатур, но заставляет каждый кодовый путь,
обходящий context, знать о не-entity entry:

- state key/render/diff;
- copying effects;
- initial builders;
- invariant applicability;
- query scans;
- scenario/flow contexts;
- affects/show/characterization.

Недавняя presence серия уже показала стоимость неявных разновидностей context
keys. Добавление ещё одной разновидности через sentinel повышает риск
false-green.

Если event state действительно нужен, лучше явный тип:

```text
WorldState:
  entities
  pending_events
```

или хотя бы отдельный immutable event-pool argument в kernel/explorer. Не стоит
оптимизировать migration cost ценой дальнейшего размытия state contract.

### P2. `event_class_id` должен быть стабильным и identity-safe

Файл:

- `research/22-event-dispatch.md:50`

Не определено, что такое `event_class_id`.

- `id(class)` сохраняет identity, но нестабилен между runs и сломает
  characterization hashes.
- `__name__` стабилен, но уже доказанно небезопасен для composition.
- qualified name может совпасть при ошибочном double import.

Для внутреннего state key можно использовать canonical registry index из
`spec.events`, а для render — qualified label плюс registry identity. Этот
контракт должен быть задан до реализации.

### P2. Research/22 противоречит собственному evidence gate

Файлы:

- `ROADMAP.md:311`
- `research/22-event-dispatch.md`

ROADMAP прямо говорит: event pool — только по результатам двух внешних моделей.
Таких evidence models ещё нет; taskboard и fulfillment созданы внутри проекта и
не являются независимым change-oriented benchmark.

Research/22 уже фиксирует implementation decision «consume без consumes=».
Это преждевременно и ослабляет роль roadmap как главного документа.

## Design Recommendation

### Что делать сейчас

1. Закрыть canonical presence bug и унифицировать invariant applicability.
2. Завершить P3 honesty pass без новой semantics:
   - `on`, `by`, `requires` явно metadata в модели, README, show/JSON;
   - не использовать слова subscribe/trigger там, где поведения нет;
   - при необходимости пометить `on` как experimental/deprecated.
3. Сделать первый внешний change-oriented evidence case из ROADMAP:
   GitHub protected pull-request policy.
4. Провести те же изменения требований в analint и Quint/FizzBee и записать:
   authoring diff, найденные ошибки, trace quality, state count и стоимость
   изменения.

Это проверяет основную нишу — verifiable domain spec для агента — не раздувая
state model.

### Когда возвращаться к events

Только если внешний case реально требует event causality, а status/state
protocol оказывается недостаточен. Тогда сначала дополнить research/22:

1. Event или Message: broadcast fact vs consumable resource.
2. Any/all semantics для `on`.
3. Pool capacity/multiplicity bound.
4. Optional transition vs automatic/fair dispatch.
5. Payload timing: pre или post.
6. Bare-class payload policy.
7. Scenario/Flow event occurrence binding.
8. Stable state encoding.
9. Delivery properties: pending, dead-letter, handled-once/at-least-once.

После этого сделать маленький prototype вне основного engine и оценить graph
growth на fulfillment.

### Если нужен минимальный operational вариант

Самый ограниченный безопасный вариант:

- один `on: EventType | None`, не список;
- synchronous one-step handoff без persistent multiset;
- handler invocation явен в Flow/Scenario;
- explorer рассматривает emit→handler как составной transition;
- никакой очереди, fan-out, retry или fairness.

Он менее универсален, зато не создаёт неограниченное измерение state. Но даже
его следует делать только после evidence case.

## Что сделано хорошо

- Предыдущие Flow/Scenario identity false-green закрыты.
- Presence applicability пересчитывается после каждого Flow/Scenario state.
- `FlowEntry` union подтверждает правильный отказ от base `Step`.
- Partial snapshot semantics теперь явно отделена от canonical initial.
- Research/22 правильно замечает, что `on` нельзя оставлять выглядящим
  operational при отсутствии поведения.
- План учитывает migration существующего taskboard, а не скрывает breaking
  change.

## Проверка

```text
.venv/bin/pytest -q              287 passed, 1 skipped
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

Подтверждённые probes:

```text
Flow absent -> Create -> invariant         PASS
foreign Scenario Action identity           structural ERROR
foreign required Action identity           structural ERROR
foreign emits/on Event identity            structural ERROR
canonical present -> Delete -> invariant   false FAIL (remaining bug)
required-payload Event emitted as class    accepted (dispatch blocker)
```

## Итоговый порядок

```text
P0  canonical invariant presence fix
P1  metadata honesty for on/by/requires
P2  external GitHub-policy evidence model + comparison
P3  decide whether events are facts, messages, or unnecessary
P4  only then implement bounded operational semantics, if evidence supports it
```

---

## Resolution

Принято полностью. Закрыто коммитами `373b46d` (P0) и `ad865bf` (P1 honesty +
разворот event-dispatch). P0-баг воспроизведён пробой до фикса.

- **P0/P2 (presence applicability)** — вынесен единый
  `state_checks.invariant_is_applicable(inv, context)` (presence-aware), и
  используется в трёх местах: `check_invariants` (scenario/flow),
  `_report_invariant_violations` (explorer per-state) и `_verify_one_invariant`
  (canonical scanner). Раздвоение устранено; false-FAIL после `Delete` исчез.
  Regression: present root → Delete → invariant над удалённым slot = PASS.
- **Event-dispatch направление** — согласен со всеми блокерами; research/22
  дополнен секцией «Разворот»: операционный `on` отложен за evidence-gate
  (мультимножество-пул не ограничен конечным payload; consume меняет смысл
  `Event`; ломает state-chaining саги fulfillment/taskboard; нет внешних
  моделей; неопределены any/all, occurrence-binding, payload timing — kernel
  считает по post, не pre, — bare-class payload, стабильный event id).
- **P1 honesty pass** — `by`/`on`/`requires` явно documentary в docstrings
  Action/Event, README и structural-warning (без «triggers/subscribe»); ROADMAP
  P3 переписан, операционный `on` помечен evidence-gated.

Не сделано (по плану ревью, отдельные шаги): внешняя GitHub-policy evidence-
модель + сравнение с Quint/FizzBee (следующий крупный шаг).

Проверка: `uv run pytest` — 288 passed, 1 skipped; `ruff check`,
`ruff format --check`, `ty check` зелёные.

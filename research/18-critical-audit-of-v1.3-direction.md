# Критический аудит разворота v1.3

Дата: 13 июня 2026.

Этот документ проверяет research/17 и последний roadmap не на внутреннюю
согласованность, а на соответствие текущему коду и реальным рискам проекта.
Он не отменяет правильную часть разворота: JSON-IR, тяжёлый мост к коду,
standalone semantic diff и Rust действительно преждевременны. Но порядок
ближайших работ в research/17 пропускает более серьёзные false-green и
предлагает автоматические проверки, для которых у модели пока нет семантики.

`ROADMAP.md` остаётся источником истины по приоритетам. Research/17 сохраняется
как журнал первого разворота; этот документ — его errata и уточнение.

---

## 1. Что в research/17 правильно

1. **Rust и внешний JSON-IR понижены обоснованно.** Реальные модели ещё не
   упёрлись в производительность, второго frontend/backend нет.
2. **Тяжёлый bridge к реализации не должен опережать сам движок.** Модель,
   которая не имеет единой семантики перехода, рано использовать как oracle
   для conformance testing.
3. **Многошаговые примеры нужны.** Quint выделяет `run` как конечную
   последовательность actions; текущий Coin уже вынужден вручную подставлять
   post-mint snapshot вместо исполнения `mint → send`.
4. **`emits/on` нельзя оставлять в двусмысленном состоянии.** Поле, которое
   выглядит операционным, но не влияет на exploration, подрывает доверие.
5. **ROADMAP как status/priority SSOT — правильное организационное решение.**

---

## 2. Пропущенные false-green

### 2.1. Explorer игнорирует `Action.post`

`scenario_runner` проверяет postconditions после effect, а `explorer` —
нет. Explorer выполняет:

```
pre → effect → Field constraints → Lifecycle transitions → invariants
```

`action.post` используется только при построении initial context dependencies
и структурном анализе. Действие с заведомо ложным `post` остаётся допустимым
переходом BFS, а query может вернуть PASS.

Это выше verification-by-default: автоматический запуск неполной семантики
только масштабирует ложный зелёный.

### 2.2. `INCONCLUSIVE` превращается в общий `passed: true`

`ValidationResult.has_errors` считает ошибкой только query со статусом `FAIL`.
`INCONCLUSIVE` не влияет на exit code, а JSON reporter вычисляет:

```python
"passed": not result.has_errors
```

Итог: ограничение `max_states` может быть достигнуто, query честно называется
`INCONCLUSIVE`, но весь `analint check` и CI остаются зелёными. Нужен общий
трёхзначный verdict (`PASS | FAIL | INCONCLUSIVE`) либо как минимум
non-zero exit для inconclusive по умолчанию.

### 2.3. Scenario runner и explorer имеют разные transition semantics

Помимо `post`:

- scenario runner не проверяет, что effect совершил разрешённый
  `Lifecycle`-переход; explorer проверяет;
- terminal guard учитывает только `Set/Add/Subtract`, но не `Delete`;
- emitted payload в scenario фактически сводится к проверке класса события;
- event, actor и ordering semantics расходятся или отсутствуют.

Правильный фикс — не добавлять проверки по одной в два движка, а выделить один
внутренний `step(action, context)` с единым результатом: rejection, post-state,
emitted events и findings. Scenario, Flow и explorer должны использовать его.
Это внутренняя semantic boundary, но ещё не внешний JSON-IR.

---

## 3. Почему verification-by-default пока не определён

### 3.1. У `Spec` нет канонического `Init`

Начальное состояние задаётся отдельно в каждом query через `given`,
`given_any` или `initial`. Поэтому один `Spec` сейчас не определяет одну
transition system: разные queries могут исследовать разные системы.

До автоматической проверки нужен spec-level initial relation:

```python
Spec(initial=Initial(...))
```

Query-specific initial state может остаться явным override для эксперимента.
Без этого «проверить систему автоматически» означает «молча выбрать defaults»,
что может проверить не ту систему.

### 3.2. Не все проверки выводимы автоматически

- `Invariant` по определению должен держаться во всех reachable states:
  его разумно проверять автоматически.
- `DeadActions` можно делать audit-warning после полного exploration.
- `NoDeadEnd` требует **явного goal**. Универсальной цели у системы нет.
- достижимость каждого lifecycle-state не обязательна: состояние может быть
  резервным, deprecated или достижимым только в другой конфигурации.
- отсутствие deadlock не равно отсутствие softlock и не всегда требуется
  терминальной системе.

Поэтому ближайшая фича — не «все verification by default», а **canonical Init
+ explicit verification policy**. PASS допустим только для реально выполненных
и завершённых проверок; остальное — `NOT_CHECKED` или `INCONCLUSIVE`.

---

## 4. `Action.by`: замечание пользователя верно, но list не решает проблему

Сейчас:

```python
by: type[Actor] | None
```

`Actor` — пустой marker class без identity и state. `by` только структурно
валидируется и показывается в introspection; на enabledness, scenario и
exploration не влияет. Поэтому проблема глубже, чем «разрешить несколько
акторов»: поле выглядит как authorization/trigger semantics, но является
документацией.

Нужно различать четыре вопроса:

1. **Кто запрашивает операцию?** Principal/identity.
2. **Кто имеет право?** Authorization predicate над principal и world state.
3. **Что вызвало переход?** Event/timer/environment trigger.
4. **Кто участвует в протоколе?** Несколько последовательных действий и state.

### Один из нескольких инициаторов

Если Customer и Admin выполняют буквально один transition, metadata могла бы
быть коллекцией. Но для проверяемой семантики лучше parameter:

```python
principal = Param("principal", users)

cancel = Action(
    params=[principal],
    pre=[In(principal.role, [Role.CUSTOMER, Role.ADMIN]), ...],
    effect=[...],
)
```

Это сохраняет identity, динамическую роль и возможность actor-specific guards.
Cedar также моделирует request через конкретный `principal`, `action` и
`resource`, отдельно предупреждая, что role не стоит использовать вместо
principal identity.

### «Только двумя вместе»

Обычно это не два инициатора одного атомарного action, а approval protocol:

```
approve(by=A) → approve(by=B) → execute
```

Approvals должны жить в state; иначе модель скроет порядок, повторное
одобрение, отзыв и race conditions. Атомарный co-sign можно выразить двумя
params с `where=[a != b]`, но отдельный core-примитив для этого не нужен.

### Решение сейчас

Не расширять `by` до list до реального кейса. Сначала выбрать одно:

- deprecate/remove `Actor/by` из semantic core и явно назвать metadata;
- либо заменить marker roles на semantic principal parameter pattern.

Оставлять текущее поле как будто оно что-то ограничивает нельзя.

---

## 5. Сценарии и идея «слоёв»

Аналогия «Scenario ≈ pytest» в основном верна:

- scenario проверяет конкретный example snapshot;
- query исследует множество reachable states;
- scenario полезен как regression/example даже при полном explorer.

Но scenario сейчас может стартовать из вручную написанного unreachable state.
Поэтому он проверяет локальную пару состояний, а не доказывает достижимость
пути.

### Что полезно

Исполняемый trace:

```
initial snapshot
→ action
→ checkpoint assertions
→ action
→ checkpoint assertions
```

Каждый следующий state обязан быть результатом настоящего transition kernel.
Quint `run` и Hypothesis state machines подтверждают ценность коротких
воспроизводимых последовательностей.

### Что пока не нужно

Рукописные «слои» как `base snapshot + arbitrary delta`. Они:

- позволяют перепрыгнуть через preconditions и invariants;
- скрывают, достижим ли новый snapshot;
- создают неявную зависимость fixture от fixture;
- уже реализуемы обычными Python helper-функциями (`_world(...)`).

Если после executable traces останется реальный boilerplate, можно добавить
named checkpoints/prefix reuse. Это эргономика, не новый semantic primitive.

---

## 6. Минимализм: концептуально да, по API уже нет

Текущий top-level `analint.__all__` содержит **48 имён**, а не восемь.
Большинство — разумные operators/effects/query types, поэтому само число не
является дефектом. Но утверждение «маленький закрытый словарь» требует
уточнения:

- conceptual kernel действительно мал: state, invariant, action, initial
  relation, property;
- authoring surface с multiplicity/presence/quantifiers уже заметно шире;
- `Actor`, `Event`, `Flow`, `requires`, `by`, `on` увеличивают словарь без
  полной операционной семантики.

Следующий этап должен повышать **semantic density**, а не добавлять слова:
каждый core primitive либо влияет на reachable behaviour, либо явно называется
annotation/tooling metadata.

---

## 7. Критика остальных выводов research/17

### State-explosion benchmark — ориентир, не основание архитектуры

Probe-скрипты не committed, hardware/runtime не записаны, а BFS использует
`list.pop(0)`, поэтому точка ~10^5 частично измеряет текущую реализацию очереди.
Вывод «Rust преждевременен» остаётся правильным, но точные числа нельзя считать
воспроизводимым benchmark до появления committed harness.

### Unbounded domains не полностью «молча усечены»

При cap query возвращает `INCONCLUSIVE` с finding про `max_states`. Реальный
баг — общий PASS/exit 0 для inconclusive. Предварительная диагностика
unbounded numeric fields полезна, но ниже по приоритету и может шуметь для
полей, которые не растут.

### Git diff и сравнение verdicts не заменяют semantic diff

Они могут не заметить новый переход, если существующие properties всё ещё
PASS. Сравнение state counts также слишком грубое. Standalone semantic diff
можно отложить, но нельзя называть эту замену эквивалентной.

### Внешняя валидация не должна быть необязательным треком

После 48 public names и закрытия P4 главный риск — не нехватка ещё одного
примитива, а создание языка под собственные examples. FizzBee уже предлагает
Python-like modeling, actors, events, model checking, visualization и MBT;
Quint имеет runs, temporal properties и MBT; P имеет event-driven machines.

Нужны минимум две модели существующих систем и прямое сравнение с Quint или
FizzBee до event pool, time, concurrency и новых domain profiles. Это не
маркетинг, а проверка архитектуры DSL.

---

## 8. Исправленный порядок работ

### P0. Semantic soundness

1. `INCONCLUSIVE` не может давать общий PASS/exit 0.
2. Один transition kernel для scenario/explorer/future Flow.
3. Explorer проверяет `post`; scenario проверяет lifecycle transition.
4. False-green tests на каждое поле `Action`.
5. Явный audit: `by/on/requires/emits` — semantics или annotation.

### P1. Canonical model

1. `Spec.initial` как единый Init relation.
2. Query initial override только явно.
3. Автопроверка invariants после полного exploration.
4. Явные `PASS/FAIL/INCONCLUSIVE/NOT_CHECKED`.
5. `NoDeadEnd(goal=...)` остаётся explicit property.

### P2. Executable traces

1. Исполняемый multi-step Flow/Scenario на общем transition kernel.
2. Assertions/checkpoints после любого шага.
3. Никаких arbitrary snapshot deltas в semantic core.

### P3. Evidence gate — начинается параллельно с P0

1. Две модели существующих систем, не придуманных под analint.
2. Один и тот же case в analint и Quint/FizzBee.
3. Измерить размер модели, время авторинга, найденные дефекты, false-green,
   понятность trace и сложность изменения.
4. Только результаты определяют судьбу Events, Actor/by, time и concurrency.

### Ниже

- event pool/message semantics;
- Computed/lifecycle guards;
- semantic diff;
- MBT bridge;
- внешний JSON-IR;
- Rust.

---

## 9. Внешние источники

- Quint language manual, включая finite `run` sequences и temporal modes:
  https://quint.sh/docs/lang
- Quint property checking: Init → reachable states → invariant:
  https://quint.sh/docs/checking-properties
- Quint model-based testing and trace replay:
  https://quint.sh/docs/model-based-testing
- Hypothesis stateful testing (short reproducible programs, invariants after
  steps): https://hypothesis.readthedocs.io/en/latest/stateful.html
- Alloy 6 specification (models as bounded traces):
  https://alloytools.org/spec.html
- FizzBee current surface (Python-like models, actors, events, MBT):
  https://fizzbee.io/
- P event-driven state machines:
  https://p-org.github.io/P/
- Cedar principal/action/resource distinction:
  https://docs.cedarpolicy.com/policies/syntax-policy.html

# Позиционирование, декларативность и аудит после v1.0

Дата исследования: 12 июня 2026.

Контекст: повторный аудит проекта после v1.0 и стресс-теста fulfillment.
Проверены текущая модель, DSL, движок, CLI/MCP, тесты, research 00-13 и
актуальный ландшафт spec-driven development и executable specifications.

Главное уточнение к предыдущим формулировкам:

> Python в analint — язык авторинга спецификации, а не язык реализации
> описываемой системы.

Модель может описывать Python-сервис, Java-систему, игровой мир, BPMN-процесс,
организационную процедуру или вообще систему без программной реализации.
Привязка к Python существует только на поверхности DSL: он даёт синтаксис,
модули, редакторы, типизацию, автодополнение и привычную агентам среду.

---

## 1. Краткий вердикт

Идея сильная и по-прежнему заслуживает развития. Текущее ядро — удачная
комбинация:

- типизированного описания состояния;
- ограничений над состоянием;
- действий как переходов `pre -> effect -> post`;
- сценариев как конкретных примеров;
- bounded reachability с короткими трассами-контрпримерами;
- агентской поверхности `show` / `affects` / MCP.

Но проект сейчас следует считать **сильным research prototype**, а не
готовым верификатором. Основная причина — не маленькая поверхность DSL, а
несколько путей к ложному зелёному результату и пока узкая модель состояния.

Оценка по направлениям:

| Направление | Оценка | Комментарий |
|---|---:|---|
| Идея и проблематика | 8/10 | Проверяемая модель поведения полезна людям и агентам |
| Архитектура понятий | 8/10 | State + predicates + guarded transitions — крепкое ядро |
| Читаемость поверхности | 8/10 | Сильнее большинства формальных DSL для целевых примеров |
| Декларативность семантики | 8/10 | Эффекты одновременны; порядок не является программой |
| Выразительность сегодня | 5/10 | Хороша для конечных синглтон-моделей, слаба для коллекций |
| Надёжность отрицательных гарантий | 3/10 | Есть silent fallback и неполная семантика explorer |
| Продуктовая готовность | 3-4/10 | Нет CI/release hygiene и внешней валидации спроса |
| Потенциал после исправления ядра | 7-8/10 | При ясном позиционировании и мосте к реализации |

---

## 2. Что именно является языком analint

Важно разделить четыре слоя.

### 2.1. Python — authoring layer

Пользователь пишет классы и значения:

```python
class Order(Entity):
    status: OrderStatus = Lifecycle(...)
    total: float = Field(ge=0)

checkout = Action(
    pre=[Order.status == OrderStatus.PENDING],
    effect=[Set(Order.status, OrderStatus.PAID)],
)
```

Python здесь выполняет роль внешнего синтаксиса и модульной системы.
Аналогичный паттерн используют embedded DSL в SQLAlchemy, Django, Pulumi,
pytest и Hypothesis.

### 2.2. Настоящий язык — построенный граф значений

После импорта остаются не «произвольные Python-программы», а ограниченный
набор значений:

```text
Entity / Field
Predicate
Invariant
Action
Effect
Event
Lifecycle
Scenario
Query
```

Именно этот граф является спецификацией. Если его можно без потерь
сериализовать в IR, семантика analint не зависит от Python.

### 2.3. IR — будущая стабильная граница

Желаемая архитектура:

```text
Python DSL ──compile──> language-independent IR ──> validators/explorers
                                            └─────> diff/visualization
                                            └─────> test/runtime adapters
```

Из этого следуют важные решения:

1. Движок не должен исполнять произвольные пользовательские функции.
2. Каждый predicate/effect должен иметь известный тип узла AST.
3. Неизвестный узел — ошибка, а не `True` и не silently skipped.
4. IR должен быть полным и версионированным.
5. Адаптер реализации может быть написан для любого языка или компонента.

### 2.4. Реализация системы — внешний объект

Спецификация ничего не предполагает о технологии реализации:

- Python/Java/Rust-сервис;
- несколько микросервисов;
- workflow engine;
- BPMN-процесс;
- ручная организационная процедура;
- игровая или нарративная система.

Поэтому формулировка «для Python-бэкендов» была слишком узкой. Точнее:

> analint — Python-authored executable model of system behaviour.

Python-команды могут быть удобным первым рынком из-за низкой цены интеграции,
но это go-to-market решение, не ограничение модели.

---

## 3. Насколько DSL декларативен

У декларативности есть несколько независимых измерений.

### 3.1. Декларативность состояния — высокая

`Entity` описывает форму состояния, а не способ его хранения или получения.
`Field` задаёт домен допустимых значений. `Lifecycle` рядом с полем задаёт
допустимую динамику.

```python
class Warehouse(Entity):
    stock: int = Field(0, ge=0, le=10)
```

Это хорошая декларативная запись: пользователь утверждает свойства мира,
а не пишет процедуру проверки диапазона.

Спорный момент: имя `Entity` несёт DDD-ассоциацию с идентичностью, хотя
формально это пока скорее **типизированный state record**. Для совместимости
имя можно оставить, но в документации не стоит утверждать, что каждый
`Entity` является DDD Entity.

### 3.2. Декларативность предикатов — высокая, но язык пока мал

```python
Wallet.balance >= Order.total
Implies(Order.status == PAID, Payment.status == CAPTURED)
```

Предикаты — значения AST, а не Python `bool` и не callbacks. Это очень
важное достоинство: их можно анализировать, сериализовать, отображать,
сравнивать и исполнять разными движками.

Ограничения:

- нет арифметических выражений как деревьев (`balance - total >= 0`);
- нет коллекций и агрегатов;
- нет кванторов;
- нет пользовательских производных выражений;
- типовая совместимость проверяется неполно.

Это снижает выразительность, но одновременно удерживает язык закрытым и
анализируемым. Расширять его нужно новыми AST-узлами, а не разрешением
произвольных Python-функций.

### 3.3. Декларативность действий — высокая семантически, средняя синтаксически

`Set`, `Add`, `Subtract` выглядят как команды:

```python
effect=[
    Set(Order.status, PAID),
    Subtract(Wallet.balance, Order.total),
]
```

Но их семантика декларативна:

- список неупорядочен;
- правые части читаются из pre-state;
- изменения применяются одновременно;
- два факта о следующем значении одного поля — структурный конфликт.

То есть `Subtract(balance, total)` следует читать как сахар для:

```text
next(balance) = balance - total
```

Это разумный компромисс между чистой реляционной записью и чтением вслух.
Однако документация должна постоянно называть эти объекты **next-state
facts**, а не operations или commands.

В будущем `field.next` полезен как низкоуровневое реляционное ядро для
недетерминизма и более общих отношений, но `Set/Add/Subtract` стоит сохранить
как читаемый сахар.

### 3.4. Декларативность событий — пока частичная

Шаблон:

```python
emits=[OrderPlaced(order_id=Order.id, total=Order.total)]
```

декларативен: он задаёт факт эмиссии и связь payload с состоянием.

Но текущий explorer не моделирует event pool. Поэтому `emits/on` сейчас
частично документация и структурная связность, а не полная операционная
семантика. Нужно либо:

- реализовать события как краткоживущие факты/ресурсы;
- либо честно отделить «domain event annotation» от переходной семантики.

### 3.5. Декларативность запросов — высокая

```python
Reachable(Order.status == SHIPPED)
Unreachable(And(Order.status == CANCELLED, Payment.status == CAPTURED))
AlwaysHolds(Warehouse.stock >= 0)
NoDeadEnd(goal=order_is_terminal)
```

Именованные запросы — хорошее решение. Они слабее полной темпоральной логики,
но намного доступнее и хорошо соответствуют практическим вопросам.

### 3.6. Главный риск embedded DSL

Python всегда позволяет написать императивный код вокруг DSL:

```python
actions = [make_action(x) for x in config]
if environment == "prod":
    ...
```

Это не делает семантическое ядро императивным. Terraform, Pulumi и ORM тоже
используют вычислительный host language. Важна граница:

> Python может конструировать модель, но не должен становиться частью
> проверяемой семантики модели.

Практическое правило: utility-функции допустимы, если их результатом являются
обычные узлы analint. Недопустимы opaque callbacks внутри `pre`, `effect`,
`Invariant` или `Query`.

---

## 4. Насколько DSL выразителен

### 4.1. Что выражается хорошо

Текущая поверхность естественно описывает:

- конечные жизненные циклы;
- guards и state transitions;
- межполевые и межсущностные ограничения;
- транзакционные правила одного случая;
- компенсационные процессы и саги для одного экземпляра процесса;
- игры и puzzle/narrative state machines;
- разрешённые и запрещённые состояния;
- достижимость, safety и отсутствие softlock;
- конкретные positive/negative examples.

Fulfillment показал, что 16 действий с компенсациями, 19 сценариев и 6
reachability-запросов укладываются примерно в 560 строк и исследуются в
34 состояниях. Это уже содержательная, а не игрушечная модель.

### 4.2. Главная граница — не DDD, а форма состояния

Сейчас состояние:

```python
dict[type[Entity], Entity]
```

То есть один экземпляр каждого типа. Это ограничивает язык сильнее всего.

Невыразимы или выражаются через ручную денормализацию:

- несколько заказов, карточек или пользователей;
- конкуренция за общий ресурс;
- «каждый X имеет Y»;
- «существует X»;
- количество, сумма, минимум/максимум коллекции;
- создание и удаление объектов;
- параметризованные действия над выбранным экземпляром;
- симметрии и связи many-to-many.

До bounded multiplicity analint — хороший язык **finite control state**,
но не универсальная модель произвольной предметной области.

### 4.3. Вторая граница — выражения

Даже в синглтон-модели скоро понадобятся:

- арифметический AST: `AddExpr`, `SubExpr`, `MulExpr`, возможно `Min/Max`;
- computed/derived expressions;
- record/value-object expressions;
- явные типы optional/sum;
- predicates над event payload и next-state;
- условные или реляционные эффекты.

Важно не превращать это в Python execution. Каждая возможность должна
оставаться сериализуемым узлом IR.

### 4.4. Третья граница — время и concurrency

Текущий explorer исследует последовательности атомарных действий. Это
подходит для бизнес-процессов, workflow и многих игр, но не моделирует:

- interleavings внутри действия;
- asynchronous delivery semantics;
- fairness;
- retries, duplicates и reorder сообщений;
- clocks, deadlines и durations;
- probabilistic outcomes.

Эти возможности не обязательно нужны ядру. Но документация должна различать
«проверка абстрактного поведения системы» и «проверка распределённого
протокола со всеми interleavings».

### 4.5. Итоговая оценка выразительности

Текущий синтаксис выразителен **относительно своего маленького словаря**:
почти каждая строка несёт предметный смысл, церемонии мало, композиция
предикатов ясна.

Но формальная выразительность пока намеренно ограничена:

```text
finite typed state variables
+ quantifier-free predicates
+ guarded simultaneous assignments
+ bounded graph exploration
```

Это не недостаток сам по себе. Опасно только называть такую модель
универсальной без явного bounded scope и списка ограничений.

---

## 5. Сравнение с Quint и P

### 5.1. Quint

Quint семантически **декларативен**, а не императивен. Он основан на
семантике TLA+: action задаёт отношение текущего и следующего состояния:

```quint
action advance(unit: int): bool =
  timer' = timer + unit
```

В языке явно разделены stateless/state/action/run/temporal modes. Есть sets,
maps, lists, records, sum types, параметры, non-deterministic choice,
temporal operators и model checking.

Почему он может восприниматься как императивный:

- отдельный programming-language syntax;
- блоки, `if`, `def`, lambdas, higher-order operators;
- delayed assignments и run mode;
- поверхность существенно шире analint.

Но это сходство синтаксиса, не семантики. В action mode обновления остаются
реляционными фактами о следующем состоянии.

Преимущество Quint:

- намного большая выразительность;
- зрелая формальная база;
- nondeterminism и temporal properties;
- model-based testing;
- LLM tooling.

Преимущество analint:

- меньше словарь;
- предметные понятия `Entity/Invariant/Action/Event/Lifecycle/Scenario`;
- Python IDE/tooling без изучения новой грамматики;
- более прямое чтение бизнес-, игровыми и процессными терминами;
- естественное соседство scenarios, field constraints и impact analysis.

Следовательно, позиция «Quint императивен, analint декларативен» неверна.
Честная позиция:

> Quint — общий современный язык executable specifications; analint может
> стать более узким, domain-shaped embedded DSL с меньшей ценой входа.

### 5.2. P

P ближе к operational state-machine programming:

- communicating machines;
- handlers;
- events;
- explicit control states;
- systematic exploration interleavings.

Он особенно силён для distributed/event-driven systems. В 2026 у P уже есть
PeasyAI через MCP и PObserve для сверки production logs со спецификацией.

По сравнению с P analint:

- менее операционен;
- не требует разложить систему на communicating machines;
- лучше подходит для глобальных предметных фактов и guarded transitions;
- значительно слабее в concurrency, message ordering и runtime conformance.

### 5.3. Вывод из конкуренции

Внутреннее утверждение research/08 «проверяемая спека для агентов — пустая
ниша» к июню 2026 устарело.

Спрос подтверждён, но появились прямые соседи:

- GitHub Spec Kit, Kiro, OpenSpec — structured NL/Markdown SDD;
- Quint — executable relational specifications + LLM/MBT;
- P — formal event-driven models + AI + runtime monitoring;
- Hypothesis stateful testing — генерация последовательностей действий
  против реализации.

Это не отменяет analint. Оно заставляет точнее назвать преимущество:

> Не «единственная проверяемая спека для агентов», а «минимальный
> domain-shaped язык поведения поверх готовой Python-экосистемы».

---

## 6. Нужно ли связывать analint с DDD

### 6.1. DDD хорошо описывает один важный профиль

Совпадение действительно сильное:

| DDD | analint |
|---|---|
| Entity / Aggregate state | `Entity` + context |
| Invariant | `Invariant` |
| Command/Application operation | `Action` |
| Domain Event | `Event` |
| Process Manager / Saga | actions + events + lifecycles |
| Ubiquitous Language | имена классов, полей, действий и предикатов |
| Bounded Context | будущая композиция spec modules |

Для enterprise/backend-аудитории фраза «executable domain model» или
«checkable tactical DDD» понятна и полезна.

### 6.2. Но DDD не должно определять ядро

DDD — метод проектирования сложного software domain. analint шире:

- в игре `Hero`, `Door`, `Quest` не обязаны быть DDD Entity/Aggregate;
- в BPMN-процессе состояние может принадлежать процессу, а не domain object;
- в системной архитектуре узел может обозначать сервис, очередь или lock;
- в организационной процедуре «Actor» может быть ролью человека;
- в протоколе переменная состояния вообще не является сущностью.

Если сделать DDD идентичностью продукта, появятся ложные обязательства:

- искать aggregate roots;
- различать Entity и Value Object;
- моделировать repositories/services;
- спорить о bounded contexts там, где это не нужно;
- воспринимать язык как инструмент только для business backend.

### 6.3. Рекомендуемая иерархия понятий

Фундаментальная модель:

```text
state + facts + transitions + observations + queries
```

Публичный универсальный словарь:

```text
Entity + Field + Invariant + Action + Event + Lifecycle + Scenario
```

DDD — интерпретация/профиль:

```text
analint.domain
```

Другие возможные профили:

```text
analint.workflow
analint.narrative
analint.protocol
analint.systems
```

Профили не должны менять семантику. Это документация, aliases, presets и
доменные проверки поверх одного IR.

### 6.4. Практический вердикт по DDD

- Использовать DDD в примерах, статьях и одном onboarding path — да.
- Описывать analint только как executable tactical DDD — нет.
- Проектировать новые core primitives по DDD-каталогу — нет.
- Проверять каждый primitive через более общую модель состояния/переходов —
  да.

DDD здесь полезный найденный изоморфизм, но не основание языка.

---

## 7. Технический аудит доверия к движку

Baseline commit `f432c16`:

- 92 теста проходят за 0.27 секунды;
- ecommerce, taskboard, cloak и fulfillment зелёные;
- deliberately broken trollbridge даёт ожидаемые две ошибки;
- примеры проверяются примерно за 1-5 миллисекунд.

Это отличный результат для размера проекта. Но обнаружены случаи ложного
`PASS`.

### 7.1. Неизвестный predicate считается истинным

`evaluate()` возвращает `True` для незнакомого объекта. В результате:

```python
Action(pre=[object()], ...)
```

проходит scenario и structural validation.

Требование: неизвестный AST node должен быть structural error или исключением
типа `UnsupportedPredicate`, никогда не `True`.

### 7.2. Ошибки evaluation молча превращаются в отсутствие нарушения

В explorer несколько `except Exception: continue/return False`. Например,
несовместимое сравнение в `AlwaysHolds` может вернуть `PASS`, потому что
predicate не был успешно вычислен ни в одном состоянии.

Требование: различать:

- predicate вычислен в `True/False`;
- predicate неприменим из-за отсутствующего event context;
- ошибка модели/типов;
- лимит движка.

Последние два исхода должны давать `FAIL` или `INCONCLUSIVE`.

### 7.3. `Expect.FAIL` инвертирует слишком широкий класс ошибок

Сейчас сценарий с ожидаемым отказом считается успешным даже если pre прошёл,
action выполнился, но сломал postcondition или `then`.

Семантически `Expect.FAIL` должен означать ожидаемое блокирование до effects:

- invariant/pre/terminal guard отверг действие — PASS;
- effect/post/then/evaluation error — FAIL модели.

Иначе дефект реализации спецификации маскируется как ожидаемый отказ.

### 7.4. `requires` не участвует в reachability

Explorer может выполнить action с `requires=[first]` прямо из initial state.
Есть два возможных честных решения:

1. `requires` только документирует Flow и не является семантикой explorer;
2. explorer хранит history facts и включает action только после requirements.

Нельзя оставлять расхождение неявным.

### 7.5. `on=` не является trigger guard

Action с `on=[Event]`, но без predicate по payload, сейчас доступен explorer
без события. Event payload predicates, наоборот, делают действие всегда
недоступным из-за отсутствующего Event в context.

Нужно выбрать:

- полноценный event pool;
- компиляцию событий в state facts;
- явное исключение event-driven actions из обычной exploration.

### 7.6. State key требует hashable scalar values

Поле `list` приводит к `TypeError: unhashable type: 'list'`. Пока коллекции
не поддерживаются, structural validation должна отклонять неподдерживаемый
state domain до запуска explorer.

### 7.7. Конфигурация качества не является реальным gate

В `pyproject.toml` включён `mypy strict`, но baseline имеет более 160 ошибок;
ruff также не зелёный. Нет CI-конфигурации и release metadata уровня
публичного пакета.

Это не проблема концепции, но сигнал: объявленные проверки должны либо
проходить, либо быть настроены честно и постепенно.

---

## 8. Продуктовое позиционирование

### 8.1. Слишком широкая формулировка

«Универсальный формальный язык для любых систем» создаёт сравнение с
TLA+/Quint/P/Alloy по максимальной выразительности. Сегодня analint это
сравнение проигрывает.

### 8.2. Слишком узкая формулировка

«DSL для Python-бэкендов» неверно связывает модель с реализацией и отрезает
workflow, games, architecture и non-Python systems.

### 8.3. Более точная формулировка

Вариант технического позиционирования:

> A Python-embedded declarative language for modelling and checking system
> behaviour: state, invariants, transitions, scenarios, and reachability.

Вариант, ориентированный на агентов:

> A compact executable system model that humans and coding agents can inspect,
> query, change, and verify before touching implementation.

Вариант для DDD-аудитории:

> Checkable domain models and sagas, authored in Python and independent of the
> implementation language.

Ни одна из формулировок не говорит, что система реализована на Python.

---

## 9. Пересобранный roadmap

### P0. Закончить реформу Field/Lifecycle и вернуть зелёный baseline

- публичные exports, README, examples и tests используют одну версию API;
- тесты, ruff и выбранный mypy baseline запускаются в CI;
- migration не оставляет одновременно `Bounds` и `Field` semantics.

### P1. Soundness before expressiveness

- неизвестные predicate/effect/query nodes — hard error;
- evaluation errors не проглатываются;
- `Expect.FAIL` инвертирует только pre-execution rejection;
- state domains валидируются до exploration;
- задокументировать/реализовать `requires` и `on`;
- тесты специально на false green.

Это высший приоритет: продукт верификатора — доверие к `PASS`.

### P2. Явный IR

- версионированная JSON schema;
- compiler из Python object graph;
- движок работает с IR или с эквивалентным закрытым representation;
- stable IDs и source locations;
- semantic diff строится над IR.

IR закрепляет независимость от Python реализации моделируемой системы и
готовит альтернативные frontends/backends без смены семантики.

### P3. Bridge to implementation через model-based testing

Pin и semantic diff полезны для process drift, но не проверяют поведение.
Более сильный первый мост:

1. analint генерирует action traces;
2. language-specific driver отображает action на реальный вызов;
3. adapter читает observable state;
4. тест сравнивает разрешённость, результат и state transition.

Первым можно сделать Python/pytest adapter как дешёвый reference integration.
Это не делает analint Python-only: позднее появляются Java/JUnit, JS,
Rust или HTTP/BPMN adapters.

### P4. Выразительность для реальных моделей

Порядок:

1. ✅ typed arithmetic/derived expression AST;
2. ✅ parameterized actions;
3. ✅ bounded multiplicity (`Scope` + stable instance refs);
4. ✅ `ForAll/Exists/Count/Sum/Min/Max` над bounded scope;
5. ✅ declarative initial relation (`Initial(vary, where)`);
6. ✅ presence semantics (`Absent`, `Present`, active quantifier domains);
7. ✅ `Create/Delete` effects в bounded universe;
8. composition of specs / explicit contracts.

Перевод Coin на один `Account` scope сохранил прежние 216 достижимых
состояний; это первый baseline state explosion. Следующий эксперимент должен
увеличить scope и плотность связей, а не немедленно вести к переписи на Rust.

### P5. Event semantics

- event pool или другой явный formal model;
- consumption/broadcast semantics;
- payload binding;
- dead subscription и eventually handled queries;
- возможность отключить event semantics для purely documentary events.

### P6. Внешняя проверка спроса

До крупных расширений:

- две модели существующих систем, не придуманных под analint;
- хотя бы одна система не на Python;
- один workflow/game/non-software case;
- интервью с 5-10 потенциальными пользователями;
- измерить время моделирования, найденные ошибки и стоимость поддержки;
- сравнить один и тот же case с Quint или Hypothesis stateful testing.

---

## 10. Что пока не делать

- Не конкурировать с Quint полнотой языка.
- Не добавлять arbitrary Python callbacks в predicates/effects.
- Не строить все tactical DDD patterns как core primitives.
- Не начинать Rust engine до появления реально большого bounded model.
- Не ставить визуализацию выше soundness и implementation bridge.
- Не обещать проверку distributed interleavings без соответствующей модели.
- Не называть `PASS` доказательством вне явно описанного bounded scope.

---

## 11. Финальный вывод

Синтаксис analint уже является одной из самых сильных частей проекта.
Он компактный, читаемый и достаточно предметный, чтобы модель выглядела
как описание системы, а не как математическая программа.

Его преимущество не в том, что Quint якобы императивен. Quint тоже
декларативен, существенно мощнее и формально зрелее. Преимущество analint
может быть в другом:

- Python как готовая authoring environment;
- маленький закрытый словарь;
- высокая плотность предметного смысла;
- знакомые `Entity/Action/Event/Scenario`;
- простые именованные verification queries;
- agent-friendly introspection и контрпримеры;
- независимость модели от языка реализации системы.

DDD полезен как важный профиль и язык общения с частью аудитории, но делать
его фундаментом не следует. Фундамент analint проще и шире:

> состояние, факты, переходы, наблюдения и запросы.

Если сначала закрыть false-green пути, провести границу через IR и построить
model-based bridge хотя бы для одного реального implementation adapter,
у проекта будет не только интересная идея, но и проверяемое отличие от
Markdown SDD с одной стороны и тяжёлых general-purpose formal languages
с другой.

---

## Источники, проверенные при аудите

- GitHub Spec Kit: https://github.com/github/spec-kit
- Kiro Specs: https://kiro.dev/docs/specs/
- OpenSpec: https://github.com/Fission-AI/OpenSpec
- Quint language and semantics: https://quint.sh/docs/lang
- Quint model-based testing: https://quint.sh/docs/model-based-testing
- Quint LLM Kit: https://github.com/quint-co/quint-llm-kit
- P language/framework: https://p-org.github.io/P/
- PeasyAI for P: https://p-org.github.io/P/getstarted/peasyai/
- PObserve runtime conformance: https://p-org.github.io/P/advanced/pobserve/pobserve/
- Hypothesis stateful testing:
  https://hypothesis.readthedocs.io/en/latest/stateful.html

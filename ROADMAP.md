# analint — Roadmap

Текущее состояние: **v0.3** — snapshot verification. Есть Entity, BusinessRule, UseCase,
Scenario (given + expected pass/fail), Spec. Линтер проверяет правила против снимка данных.

---

## v0.4 — Чистка фундамента

Технический долг перед следующими фичами. Небольшой объём, высокая ценность.

### Predicate → dataclass
Убрать pydantic из predicate.py. `_Gte`, `_Eq` и т.д. — обычные `@dataclass`.
`kind`-поле и discriminated union не используются нигде в рантайме — мёртвый код.

### rule_type с реальной семантикой
Сейчас `BusinessRule` имеет `rule_type` как строку без смысла.
Ввести три типа с разным поведением линтера:

| Тип | Когда проверяется |
|---|---|
| `Invariant` | Всегда — в каждом сценарии, независимо от UC |
| `Precondition` | Перед запуском UseCase |
| `Postcondition` | После применения эффектов UseCase |

**DSL:**
```python
rule_price = BusinessRule(..., rule_type=RuleType.INVARIANT)
rule_funds = BusinessRule(..., rule_type=RuleType.PRECONDITION)
rule_paid  = BusinessRule(..., rule_type=RuleType.POSTCONDITION)
```

---

## v0.5 — StateMachine + Effects

Добавляет **время** в модель. Сущности перестают быть статичными снимками.

### StateMachine
Описывает жизненный цикл entity-поля: какие переходы между состояниями возможны
и какой UseCase их вызывает.

**DSL:**
```python
class OrderLifecycle(StateMachine):
    entity  = Order
    field   = Order.status
    initial = OrderStatus.PENDING

    transitions = [
        Transition(OrderStatus.PENDING,  OrderStatus.PAID,      via=uc_checkout),
        Transition(OrderStatus.PAID,     OrderStatus.SHIPPED,   via=uc_ship),
        Transition(OrderStatus.PENDING,  OrderStatus.CANCELLED, via=uc_cancel),
    ]
```

**Линтер проверяет:**
- Нет переходов в/из неизвестных состояний
- Нет "тупиков" — состояний без выхода (если это не финальное состояние)
- Сценарий задаёт начальное состояние, недостижимое по StateMachine → предупреждение

### Effects на UseCase
UseCase декларирует что меняется после его выполнения.
Effects — это связующее звено между UseCase и StateMachine.

**DSL:**
```python
uc_checkout = UseCase(
    ...
    effects=[
        Set(Order.status, OrderStatus.PAID),
        Subtract(Wallet.balance, Order.total),
    ],
)
```

**Линтер проверяет:**
- `Set(Order.status, X)` — переход в X должен быть в StateMachine с `via=этот UC`
- Postconditions проверяются после применения Effects к снимку данных

---

## v0.6 — Actor + Requires + Event

Делает UseCase самодостаточным описанием бизнес-операции.

### Actor
Кто может запустить UseCase. Не только документация — линтер может проверить
что в flow не происходит вызова UC не тем актором.

**DSL:**
```python
class Customer(Actor): pass
class Admin(Actor): pass

uc_checkout = UseCase(..., actor=Customer)
uc_refund   = UseCase(..., actor=Admin)
```

### Requires — зависимость по времени
UseCase может запускаться только если другой UC уже завершился.
Это не просто документация — используется при валидации Flow.

**DSL:**
```python
uc_checkout = UseCase(..., requires=[uc_login])
uc_payment  = UseCase(..., requires=[uc_checkout])
```

**Линтер проверяет:**
- Нет циклических зависимостей
- В Flow шаги идут в порядке, совместимом с `requires`
- Сценарий запускает UC без выполнения `requires` → ошибка

### Event — слабая связность между UC
UseCase может эмитировать события и подписываться на них.
Это альтернатива жёсткому `requires` для асинхронных процессов.

**DSL:**
```python
class OrderPlaced(Event):
    order_id: str
    total: float

uc_checkout = UseCase(..., emits=[OrderPlaced])
uc_payment  = UseCase(..., triggered_by=[OrderPlaced])
uc_notify   = UseCase(..., triggered_by=[OrderPlaced])
```

**Линтер проверяет:**
- Каждое emitted событие подхвачено хотя бы одним UC
- Поля события существуют и типы совместимы
- Нет "потерянных" событий

---

## v0.7 — Flow + When/Then в сценариях

Самый сложный и ценный milestone. Связывает всё вместе.

### Flow
Описывает последовательный пользовательский путь с ветвлениями.

**DSL:**
```python
flow_checkout = Flow(
    id="happy-checkout",
    steps=[
        uc_login,
        uc_browse,
        uc_add_to_cart,
        Branch(
            If(Product.stock > 0, then=[uc_checkout, uc_payment]),
            Else([uc_out_of_stock_notice]),
        ),
    ],
)
```

**Линтер проверяет:**
- Postconditions шага N логически совместимы с Preconditions шага N+1
- `requires` всех UC соблюдён порядком шагов в flow
- Актор не меняется внутри flow без явного указания

### Scenario: When + Then
Сценарий перестаёт быть просто "данные + pass/fail".
Появляется `When` (что делает пользователь) и `Then` (что должно быть после).

**DSL:**
```python
sc_happy = Scenario(
    id="checkout/happy",
    given=[
        Order(total=50.0, status=OrderStatus.PENDING),
        Wallet(balance=100.0),
        Product(stock=5, price=50.0),
    ],
    when=Run(uc_checkout),          # или Run(flow_checkout)
    then=[
        Assert(Order.status == OrderStatus.PAID),
        Assert(Wallet.balance == 50.0),
        Emitted(OrderPlaced),
    ],
    expected=Expect.PASS,
)
```

**Что делает линтер:**
1. Проверяет Preconditions UC против `given`
2. Применяет Effects к состоянию
3. Проверяет Postconditions и `then`-утверждения
4. Сравнивает с `expected`

---

## v1.0 — System Analytics

Возврат технического слоя, теперь интегрированного с бизнес-слоем.

- `Service`, `Interaction`, `Topic`, `Queue`, `Database`, `Cache`
- UseCase связывается с сервисом-реализатором: `uc_checkout.implemented_by = order_service`
- Линтер проверяет: сервис, реализующий UC, имеет доступ к нужным ресурсам
- Topology predicates: `Reachable`, `ExclusiveWrite` (были в v0.2)

Ценность: bridge между бизнес-требованиями и архитектурой системы.

---

## Зависимости между milestone'ами

```
v0.4 (cleanup)
  └─► v0.5 (StateMachine + Effects)
        └─► v0.6 (Actor + Requires + Event)
              └─► v0.7 (Flow + When/Then)
                    └─► v1.0 (System Analytics)
```

v0.4 и v0.5 можно делать параллельно (разные части кода).
v0.6 частично независим от v0.5 (Actor и Requires не требуют Effects).
v0.7 требует всего предыдущего.

---

## Приоритет по ценности

| Milestone | Сложность | Бизнес-ценность | Что даёт |
|---|---|---|---|
| v0.4 cleanup | XS | низкая | технический долг |
| v0.5 StateMachine | M | **высокая** | жизненный цикл сущностей |
| v0.5 Effects | M | **высокая** | связь UC с изменениями |
| v0.6 Actor | S | средняя | кто делает что |
| v0.6 Requires | S | **высокая** | порядок UC |
| v0.6 Event | M | **высокая** | слабая связность |
| v0.7 Flow | L | **очень высокая** | пользовательские пути |
| v0.7 When/Then | L | **очень высокая** | полные сценарии |
| v1.0 System | XL | средняя | архитектурный слой |

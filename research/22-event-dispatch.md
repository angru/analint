# Event dispatch: making `on` operational (P3)

Дата: 14 июня 2026.

Повод: фаза v1.3 P3 («семантическая честность словаря»). Аудит показал, что
`emits` имеет поведение (kernel материализует payload, `Emitted`-checkpoint
проверяет), а `by`/`on`/`requires` — documentary metadata, которые *выглядят*
как поведение. Решение (с пользователем): дать реальную семантику **одному**
элементу — `on` — как event-dispatch, напрямую (без отдельного `consumes=`).

## Семантика

Consume-модель (не broadcast):

- `emits=[E(field=expr)]` кладёт материализованное событие `E` в **event pool**
  следующего состояния (payload вычисляется против pre-state, как сейчас).
- `on=[E]`-действие **enabled** ⇔ в пуле есть ожидающее `E`; срабатывание
  **потребляет** одно `E` (биндит его в контекст под ключом класса `E`, чтобы
  `pre`/`effect` читали payload-поля, как уже делают сценарии), и убирает его из
  пула в post-state.
- Несколько ожидающих `E` ⇒ ветвление в explorer (по одному преемнику на выбор),
  как `Param`/`given_any`. В сценарии событие приходит в `given` — выбор
  детерминирован.

Это подключает `emits`→`on` и **включает event-driven actions в exploration**
(сейчас они исключаются: «event payloads outside the engine's state model»).

## Конечность (finiteness)

Пул — мультимножество материализованных событий. BFS конечен только если payload
конечен: каждое поле события — enum/bool/Field-bounded. Иначе пул растёт без
границ → exploration упирается в `max_states` → честный `INCONCLUSIVE` (та же
деградация, что у безграничных числовых доменов). Структурное предупреждение:
событие с потенциально безграничным payload, используемое в `on`.

## Представление состояния

«Состояние» становится `entities + event pool`. Чтобы не переписывать сигнатуры
повсюду, пул живёт в `context` под sentinel-ключом (не Entity/InstanceRef).
Точки, перечисляющие сущности контекста, его обрабатывают явно:

- `state_key` — включает отсортированный, хешируемый снимок пула; пропускает
  sentinel в цикле сущностей;
- `render_state` — рендерит пул;
- `_apply_effects` (kernel) — копирует сущности, отдельно ведёт пул (consume +
  emit);
- builders/инвариант-итерация — sentinel не сущность, в предикатах не
  встречается, поэтому в `set(context)`-надмножестве безвреден.

Пул — отсортированный кортеж `(event_class_id, sorted-payload-items)`; порядок не
значим (consume берёт по совпадению класса).

## Влияние на существующее

`on` сейчас документальный: taskboard `send_notification` имеет
`on=[CardCreated, ...]`, но срабатывает по состоянию `Notification`
(`pre=[notification_unread]`), не по событию. Операционный `on` потребует
ожидающее событие — это **меняет** поведение, поэтому `send_notification`
переписывается под новую модель (или его `on` снимается, если реакция на
состояние — это намеренно не dispatch). Решение: переписать пример под честную
dispatch-модель.

## Фазовый план

- **A.** Event pool в состоянии + `state_key`/`render`/`_apply_effects`; kernel:
  emits→пул, on-action consume (читает payload, убирает из пула). Unit-тесты.
- **B.** Explorer: убрать исключение on-actions; перебор ожидающих событий
  (branch), bind, step, преемник с обновлённым пулом; finiteness → INCONCLUSIVE.
- **C.** Выровнять scenario/flow; переписать taskboard; show/affects, README,
  AGENTS, characterization; состязательные пробы на false-green.

## Что осознанно НЕ делаем

- broadcast / fan-out (одно событие → все handler'ы) — сложнее «завершённость»;
  consume проще и верифицируем.
- time/concurrency примитивы — остаются за evidence-gate.
- `by`/`requires` — остаются documentary (отдельный honesty-pass позже).

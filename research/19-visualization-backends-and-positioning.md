# Визуализация, backends и честная ниша относительно Quint/FizzBee

Дата исследования: 13 июня 2026.

Контекст: после critical audit (research/18) появились три связанные гипотезы:

1. визуализация, интерактивный запуск и статистика могут помочь понимать модель;
2. единое представление модели может позволить несколько execution backends;
3. analint рискует повторять Quint или FizzBee с Python-синтаксисом.

Краткий вывод:

- диагностическая визуализация полезна, но не усиливает доказательство сама по
  себе;
- первым артефактом должен быть машиночитаемый exploration result, а не UI;
- несколько backends требуют нормализованной семантической модели, но не
  обязательно внешнего JSON-IR;
- Numba не подходит к текущему object-heavy explorer без отдельного lowering;
- пересечение с Quint/FizzBee велико. Самостоятельная ниша analint пока
  является проверяемой гипотезой, а не установленным фактом.

---

## 1. Что именно даёт визуализация

Model checker уже отвечает на формальный вопрос независимо от картинки.
Визуализация не превращает `INCONCLUSIVE` в доказательство и не компенсирует
неполную transition semantics.

Она полезна как **model-debugging interface**:

- показывает неожиданно разрешённые и недоступные действия;
- делает видимыми циклы, тупики, узкие места и сильно ветвящиеся состояния;
- помогает заметить потерянный lifecycle edge или слишком слабый guard;
- показывает, какие поля действительно менялись на trace;
- позволяет человеку проверить, совпадает ли абстрактная модель с его
  пониманием системы;
- даёт агенту компактный структурированный артефакт вместо полного дампа BFS.

Это обнаруживает ошибки **описания модели**, но не является новым способом
верификации.

### Что визуализировать

Нужны разные представления, а не один огромный state graph:

1. **Trace view** — последовательность действий, state diff каждого шага,
   нарушенное условие и причина disabled action.
2. **Lifecycle graph** — состояния и объявленные переходы одного поля.
3. **Action dependency graph** — reads/writes/events/requires/contracts.
4. **Exploration summary** — агрегаты по графу.
5. **State graph** — только для малых моделей или после фильтрации/агрегации.

Полный граф из десятков тысяч состояний практически не читается. Рисовать его
по умолчанию — эффектная, но слабая функция.

### Полезная статистика

- число roots, states, edges и максимальная глубина;
- capped/inconclusive status, время и память;
- branching factor: min/mean/max и распределение;
- сколько раз каждое action было enabled/fired;
- dead actions и непокрытые lifecycle edges;
- observed domain каждого поля;
- dead ends и strongly connected components;
- самый короткий trace к каждому нарушению;
- доля времени на state encoding, predicate evaluation, copying и queue.

Последний пункт — performance telemetry движка, а не характеристика модели.
Не следует смешивать его с предметными метриками вроде latency/cost:
вероятностная и performance semantics — отдельное расширение языка.

---

## 2. Порядок реализации visualization track

### V0. Exploration artifact

После общего transition kernel определить стабильный **result artifact**:

```text
roots
nodes: state id + rendered fields
edges: source + action id + target + binding
findings
traces
summary
completeness: complete | capped | excluded-semantics
```

Это не model IR. Это результат конкретного запуска с конкретными bounds.
Его можно отдавать через CLI JSON, MCP, DOT/Mermaid exporter и будущий UI.

### V1. CLI-first diagnostics

- `analint trace ...` или trace section существующего `check`;
- `analint graph lifecycle ... --format mermaid|dot`;
- `analint explore --format json` с summary;
- state diff вместо полного повторения snapshot на каждом шаге.

### V2. Interactive explorer

Пользователь начинает с canonical initial state или выбранного допустимого
root, видит enabled actions, выбирает binding, шагает, откатывается и создаёт
ветку. Для disabled action показывается конкретная failed precondition.

Начинать с произвольного snapshot можно только как явно помеченный
`hypothetical` режим: такой state может быть недостижим. Идея arbitrary state
layers не нужна. Переиспользуемые checkpoints должны быть получены
исполняемыми traces.

FizzBee уже демонстрирует полезность такого Explorer: выбор действий,
последовательности состояний и sequence diagrams. Quint REPL позволяет
интерактивно применять действия и наблюдать state. Поэтому generic explorer
не является уникальным преимуществом analint; он является ожидаемым UX.

---

## 3. IR, JSON и backends — четыре разные границы

Термин `IR` использовался слишком широко. Нужно различать:

1. **Authoring graph** — Python-классы и DSL-объекты пользователя.
2. **Normalized semantic model** — закрытые узлы, над которыми работает
   transition kernel.
3. **Execution plan** — компактное backend-specific представление: integer
   slots, opcodes, domains, indexes.
4. **Wire format** — версионированный JSON/Protobuf для обмена между процессами.

Второй backend требует пункты 2 и 3. Он не требует публичного JSON.
Визуализация результата требует JSON exploration artifact, но не JSON модели.

Публичный JSON-IR нужен, когда появляется хотя бы один реальный consumer:

- внешний backend в другом процессе/языке;
- второй frontend;
- воспроизводимое архивирование модели независимо от Python environment;
- remote service или кэш компиляции;
- внешний visualizer, которому нужна модель, а не только result artifact.

До этого internal dataclasses дешевле менять и труднее случайно объявить
стабильным контрактом.

### Возможные backends

- reference explicit-state BFS на Python — эталон семантики;
- optimized explicit-state backend — компактное состояние и быстрый successor
  generation;
- simulator — sampling без гарантии полноты;
- symbolic/SMT backend — bounded path constraints для больших числовых доменов;
- exporter в существующий verifier, если сохраняется trace mapping.

Backend обязан возвращать одинаковую модель verdicts:
`PASS / FAIL / INCONCLUSIVE / NOT_CHECKED`, completeness metadata и witness.
Иначе это не взаимозаменяемые backends.

---

## 4. Почему Numba не является ближайшим ускорением

Текущий explorer использует:

- словари с ключами-классами и `InstanceRef`;
- Python Entity instances и `copy.copy`;
- dataclass AST с динамическим dispatch;
- Enum и heterogeneous tuples;
- обход всех actions для каждого state;
- `list.pop(0)` как очередь.

Numba силён на числовых массивах и типизированных циклах. Чтобы он помог,
модель сначала придётся скомпилировать в integer slots, typed arrays и opcodes.
После такого lowering можно честно сравнить:

- pure Python над компактным plan;
- Numba;
- Rust;
- Cython/mypyc;
- vectorized или parallel exploration.

До профиля реальной модели выбор технологии является гаданием.

Ближайшие ускорения дешевле и архитектурно нейтральнее:

1. `collections.deque` вместо `list.pop(0)`;
2. компактный state key без повторного обхода descriptors;
3. предкомпилированные predicate/effect evaluators;
4. индексирование actions по зависимостям;
5. symmetry reduction для однотипных instances;
6. partial-order reduction для независимых actions;
7. только затем parallelism/JIT/native backend.

Главное: ускорение на порядок не лечит экспоненциальный state explosion.
Reduction techniques обычно важнее смены языка.

---

## 5. Насколько analint повторяет Quint/FizzBee

Ответ: **существенно повторяет**.

Quint уже предлагает:

- executable transition-system specifications;
- invariants, temporal properties, nondeterminism и runs;
- simulator, REPL и counterexample traces;
- Apalache и TLC как разные verifier backends;
- JSON intermediate transpiler outputs;
- model-based testing, Rust Connect и LLM tooling;
- Choreo как domain-shaped framework для distributed protocols.

FizzBee ещё ближе к исходной интуиции analint:

- Python-like authoring;
- actions, roles/actors, assertions и model checking;
- online playground и interactive Explorer;
- sequence/block diagrams;
- probabilistic/performance modeling;
- model-based testing и AI assistant skills.

Поэтому следующие формулировки не выдерживают сравнения:

- «формальная модель с понятным синтаксисом»;
- «Python-подобная спецификация»;
- «model checking для обычных разработчиков»;
- «визуализация и генерация traces»;
- «спека для AI-агентов».

Все они уже заняты.

---

## 6. Возможная самостоятельная ниша

Рабочая гипотеза:

> analint — schema-first domain contract linter для долгоживущих моделей
> продукта/workflow, оптимизированный под безопасные изменения человеком и
> coding agent, а не general-purpose formal language.

Содержательные отличия, которые уже есть или естественно следуют из ядра:

- фиксированный domain vocabulary: `Entity`, field constraints, `Lifecycle`,
  `Invariant`, `Action`, `Scenario`, `Contract`;
- explicit contracts и композиция reusable fragments;
- impact analysis `affects`, структурированная `show`-интроспекция и MCP;
- what-if overlay до изменения основной спеки;
- одновременные effects и field-level structural diagnostics;
- единая модель как проверяемая база знаний для change workflow;
- намеренно ограниченная expressive surface вместо TLA-level algebra.

Это не технологический moat. Quint/FizzBee могут добавить аналогичное
tooling. Ценность должна подтверждаться тем, что типичная продуктовая правка
в analint:

- моделируется быстрее;
- ревьюится понятнее;
- имеет меньший blast radius;
- даёт агенту более точный change context;
- реже требует знания formal-methods concepts.

### Где не нужно конкурировать

- distributed protocols, consensus и message interleavings;
- temporal logic как основной сценарий;
- symbolic big-integer verification;
- probabilistic/performance modeling;
- general-purpose mathematical specification.

В этих областях Quint/FizzBee/P уже имеют более сильную основу.

---

## 7. Стратегические варианты

После evidence gate возможны три честных направления:

### A. Узкий самостоятельный verifier

Сохраняем bounded domain/workflow нишу, свой explicit-state engine и
инвестируем в diagnostics/change tooling.

### B. Domain frontend над существующими backends

Python DSL компилируется в нормализованную модель, затем в Quint/TLA+/SMT.
analint владеет vocabulary, contracts, scenarios, impact analysis и agent UX,
но не пытается догнать verifier engineering нескольких зрелых проектов.

### C. Analysis layer

analint становится инструментом композиции, lint/impact/diff и model
maintenance, а проверку делегирует внешнему языку или backend.

Варианты B/C не являются поражением. Если уникальная ценность находится в
model maintenance, переписывание model checker будет отвлекать от неё.

---

## 8. Evidence gate для позиционирования

Нужен не ещё один tutorial translation, а change-oriented эксперимент:

1. взять реальный workflow/product policy;
2. описать его в analint и Quint или FizzBee;
3. внести три последовательных изменения требований;
4. измерить authoring time, diff size, понятность review, найденные дефекты,
   качество traces и объём контекста для агента;
5. проверить, дал ли `Contract/show/affects/what-if` измеримое преимущество.

Stop condition:

> Если analint не даёт явного преимущества на изменении и сопровождении
> модели, не расширять собственный язык и verifier. Использовать Quint/FizzBee
> напрямую либо перейти к варианту B/C.

Это более строгий и полезный критерий, чем «мы можем выразить тот же пример».

---

## Источники

- Quint overview, model checker/simulator и counterexamples:
  https://quint.sh/docs/what-does-quint-do
- Quint REPL:
  https://quint.sh/docs/repl
- Quint model checker backends:
  https://quint.sh/docs/model-checkers
- Quint design principles и JSON intermediate outputs:
  https://quint.sh/docs/design-principles
- Quint Choreo:
  https://quint.sh/docs/choreo
- Quint Connect:
  https://github.com/quint-co/quint-connect
- FizzBee overview:
  https://fizzbee.io/
- FizzBee repository and AI assistant skills:
  https://github.com/fizzbee-io/fizzbee
- FizzBee whiteboard/interactive Explorer:
  https://fizzbee.io/design/tutorials/visualizations/
- FizzBee performance modeling:
  https://fizzbee.io/design/tutorials/performance-modeling/
- Numba JIT model and supported surface:
  https://numba.readthedocs.io/en/stable/user/jit.html

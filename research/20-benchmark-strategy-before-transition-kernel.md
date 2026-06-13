# Benchmark-стратегия перед transition kernel

Дата: 13 июня 2026.

Повод: перед выделением общего transition kernel появились characterization
snapshot текущих examples и `scripts/bench.py`. Возник вопрос, нужен ли один
большой пример — игра или система — чтобы заметить semantic/performance drift.

## Краткий ответ

Один большой example не решает задачу. Нужны четыре разных слоя:

1. **Semantic conformance suite** — корректность одного transition.
2. **Graph characterization** — drift наблюдаемого reachable graph.
3. **Parameterized scalability benchmarks** — скорость и state explosion.
4. **External evidence models** — продуктовая ценность и позиционирование.

Перед kernel обязательны только первые два. Scalability benchmark полезен
параллельно, но не должен задерживать semantic fix. Большой внешний model
следует делать после kernel, иначе он будет написан поверх заведомо
расходящихся scenario/explorer semantics и затем переписан.

---

## 1. Semantic conformance suite — главный gate перед kernel

Тестовая матрица должна запускать один и тот же action/context через scenario
и explorer/step и сравнивать:

- accepted/rejected/model-defect;
- post-state;
- findings;
- emitted events;
- state diff.

Минимальные оси:

- pre: true / false / evaluation error;
- effect: empty / Set / arithmetic / simultaneous updates;
- presence: Create / Delete / absent target;
- Field: hard violation / saturation;
- Lifecycle: allowed / undeclared / terminal;
- post: true / false / evaluation error, включая empty effect;
- invariant: pre/post violation;
- event payload binding;
- `Expect.FAIL`: только pre-execution rejection.

Это ловит именно те ошибки, ради которых выделяется kernel. Ни размер модели,
ни число BFS states такую матрицу не заменяют.

---

## 2. Graph characterization — сильнее текущего snapshot

Текущий snapshot полезен как smoke baseline, но одинаковое число states не
означает одинаковый graph.

Стабильный normalized artifact должен включать:

```text
roots: rendered states
states: canonical rendered state set
edges: source state + bound action id + target state
fired/excluded actions
findings: severity + location + normalized message
query verdict + shortest trace
scenario id + verdict + normalized findings
```

Можно хранить JSON для малых examples или hashes отдельных sections. Hash без
читаемого diff хуже для review, поэтому малые текущие graphs разумнее хранить
явно либо выдавать diff при mismatch.

Characterization не является нормативной семантикой. Перед refactor нужно
перечислить ожидаемые изменения:

- lifecycle transition validation появляется в scenario;
- `Delete` учитывается terminal guard;
- emitted payload проверяется полноценно;
- effectless `Action.post` перестаёт обходиться;
- общий ordering проверок становится единым.

---

## 3. Performance benchmark — параметризуемые семьи, не один сюжет

Текущие examples имеют максимум 216 states. Они измеряют overhead маленькой
модели, но почти ничего не говорят о scaling.

Нужны генерируемые deterministic families:

### Counter grid

`N` независимых bounded counters с increment/decrement actions.

Ожидаемый порядок state space:

```text
(bound + 1) ** N
```

Нагружает state encoding, queue и полный action scan.

### Conserved token transfer

`N` accounts, фиксированный total supply, параметризованные transfers.

Число распределений:

```text
C(total + N - 1, N - 1)
```

Нагружает Scope/Param, simultaneous effects, quantifiers и symmetry.

### Workflow product

Несколько почти независимых lifecycle entities.

Ожидаемый graph близок к декартову произведению локальных states. Нагружает
interleavings и показывает пользу partial-order reduction.

Для каждой семьи нужны размеры примерно:

```text
small:  10^2–10^3 states   CI correctness
medium: 10^4 states        manual/default benchmark
large:  10^5+ states       stress/inconclusive boundary
```

Метрики:

- states и edges;
- complete/capped;
- wall time и peak memory;
- time per state/edge;
- branching factor;
- phase timings: enabledness/effects/keying/copying/queue.

Timing не должен быть жёстким CI gate. CI может проверять ожидаемые
states/edges для small case. Performance trend запускается вручную или на
контролируемом runner.

---

## 4. External evidence model — не performance benchmark

Первый кандидат: **GitHub protected pull-request policy** по официальной
документации.

Почему это хороший analint case:

- обязательное число approving reviews;
- code-owner approval;
- blocking requested changes;
- stale approvals после нового commit;
- approval latest push другим principal;
- required status checks;
- resolved conversations;
- admin/bypass policy;
- optional merge queue.

Это проверяет:

- principal/authorization вместо декоративного `Action.by`;
- multi-approval как protocol state;
- bounded multiplicity reviewers/checks;
- lifecycles и guards;
- contracts/composition;
- `show` / `affects` / `what-if`;
- executable traces и NoDeadEnd/Reachable properties.

Предлагаемая серия изменений:

1. Baseline: один approval + required checks.
2. Добавить code owner и dismiss stale approvals.
3. Добавить latest-pusher separation и запрет bypass.
4. Опционально: merge queue как отдельное расширение.

Сравнивать analint с Quint или FizzBee нужно не только по строкам, а по:

- времени первого описания;
- diff каждого policy change;
- найденным дефектам;
- понятности review/counterexample;
- контексту для coding agent;
- пользе `Contract/show/affects/what-if`.

Второй внешний case позднее: Stripe PaymentIntent lifecycle — асинхронные
payment states, confirm/capture/cancel и events. Он дополняет GitHub case,
проверяя lifecycle/saga/event сторону.

---

## 5. Решение по roadmap

До transition kernel:

1. исправить effectless-post bypass;
2. добавить semantic conformance matrix;
3. усилить graph characterization;
4. перечислить ожидаемые semantic delta.

Параллельно или сразу после kernel:

5. добавить synthetic scalability families;
6. снять baseline curves;
7. не выбирать Numba/Rust до профиля.

После kernel и executable traces:

8. реализовать GitHub protected-PR policy как первый change-oriented evidence
   model;
9. сравнить с Quint/FizzBee;
10. только результат определяет дальнейшее расширение DSL/backend.

## Что не делать сейчас

- не писать одну большую вымышленную игру как главный benchmark;
- не использовать timing текущих examples как performance gate;
- не считать одинаковое число states доказательством semantic parity;
- не задерживать kernel до завершения внешнего evidence model;
- не оптимизировать известные расходящиеся semantics.

## Источники

- GitHub protected branches: reviews, stale approvals, status checks, code
  owners, latest-push approval and merge queue:
  https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- GitHub merge queue:
  https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue
- Stripe PaymentIntent lifecycle:
  https://docs.stripe.com/payments/paymentintents/lifecycle
- Stripe PaymentIntent state object:
  https://docs.stripe.com/api/payment_intents/object

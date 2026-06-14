# Review: kernel fixes and canonical verification after 535ecb8..67be4f8

Дата ревью: 14 июня 2026.

Коммиты:

```text
b8da3d6 Close the semantic gaps found in review 535ecb8
1e60a04 Record resolution of the transition-kernel review
8268926 Add a canonical Spec.initial that queries fall back to
393128b Verify invariants over the canonical model automatically
6edc1fb Make mafia's canonical model the full role-assignment set
67be4f8 Mark P1 (canonical model + verification policy) done in the roadmap
```

## Verdict

Коммит `b8da3d6` качественно закрывает предыдущий review: прежние probes теперь
дают ожидаемые результаты, direct tests для `TransitionResult` добавлены,
taskboard policy завершена, ordering задокументирован как двухслойная модель.

Canonical `Spec.initial` — правильное направление, и query fallback реализован
просто и последовательно. Но статус P1 «готово» пока преждевременен:
автоматическая invariant verification имеет два подтверждённых false-green и не
показывает неполноту exploration.

Статус:

> Kernel review закрыт. Canonical verification требует ещё одного hardening
> commit до перехода к P2.

---

## Findings

### P1. Canonical exploration теряет transition defects и возвращает общий PASS

Файлы:

- `src/analint/validator/explorer.py:616`
- `src/analint/validator/engine.py:92`

`verify_invariants()` запускает `explore()`, но возвращает только список
`InvariantResult`. Все `exp.findings`, включая transition-level ERROR из
kernel, отбрасываются.

В результате invariant может получить PASS, хотя действие в canonical model
вообще не вычисляется.

End-to-end probe:

```python
class Box(Entity):
    value: int = 0

broken = Action(
    id="broken",
    effect=[Set(Box.value, Box.value + "bad")],
)
non_negative = Invariant(Box.value >= 0, id="non_negative")
```

Фактический JSON:

```text
verdict: PASS
passed: true
invariant non_negative: PASS, 1 state
exploration: []
```

Kernel при этом создаёт `effect evaluation error`; автоматическая exploration
его видит, но `ValidationResult` не получает.

Это прямой false-green: новая проверка делает утверждение о canonical model,
но скрывает найденный model defect.

Исправление должно сохранять один canonical `Exploration` artifact и передавать
его findings в `ValidationResult.exploration_findings` либо возвращать из
`verify_invariants` структурированный результат:

```text
CanonicalVerification:
  exploration
  invariant_results
```

ERROR findings обязаны делать общий verdict FAIL. Добавить end-to-end regression
для spec с invariant, broken action и без queries.

### P1. `Spec.initial` не проходит structural validation и может быть мёртвым

Файлы:

- `src/analint/models/root.py:56`
- `src/analint/validator/structural.py:409`
- `src/analint/validator/engine.py:92`

Structural validation существующего `query.initial` проверяет:

- зарегистрированные entities/scopes;
- повторяющиеся vary fields;
- refs в `where`.

Тот же `Initial`, помещённый в `Spec.initial`, не проверяется вообще.

End-to-end probe:

```python
class Registered(Entity):
    enabled: bool = False

class Foreign(Entity):
    enabled: bool = False

spec = Spec(
    id="s",
    name="S",
    entities=[Registered],
    initial=Initial(vary=[Foreign.enabled]),
)
```

Если в spec нет invariants и queries, canonical initial никто не строит:

```text
structural: []
verdict: PASS
passed: true
```

То есть корневая часть модели может быть невалидной и при этом не влиять на
результат.

Нужно вынести validation `Initial` в общий helper и применять его к:

1. `Spec.initial` с location `spec:<id>` или `initial:<id>`;
2. каждому `query.initial`.

Canonical initial следует валидировать независимо от наличия queries и
invariants.

### P1. Invariant PASS не сообщает о неполной semantics

Файлы:

- `src/analint/validator/explorer.py:374`
- `src/analint/validator/explorer.py:616`
- `src/analint/reporter/base.py:64`

Explorer явно исключает actions, чьи preconditions зависят от event payload.
Он записывает:

```text
excluded from exploration: ... event payloads are outside the engine's state model
```

Но canonical verification отбрасывает это finding и возвращает invariant PASS.

Probe:

```python
event_step = Action(
    on=[Signal],
    pre=[Signal.ok == True],
    effect=[Set(Box.value, 1)],
)
stays_zero = Invariant(Box.value == 0)
```

Фактический результат:

```text
InvariantResult: PASS
states_explored: 1
findings: []
```

При этом именно исключённый action меняет поле, которое ограничивает invariant.
Без event-pool semantics доказательство не завершено.

Минимум: сохранять excluded warning в canonical verification artifact и
показывать completeness отдельно. Более строгая policy: invariant без
контрпримера при `exp.excluded` получает `NOT_CHECKED` или `INCONCLUSIVE`, а не
PASS.

Это нужно решить явно; сейчас формулировка «invariant verified over canonical
model» сильнее фактической гарантии.

### P2. Бюджет automatic verification нельзя настроить из Spec или CLI

Файлы:

- `src/analint/validator/explorer.py:581`
- `src/analint/validator/engine.py:95`

`verify_invariants` имеет параметр `max_states=10_000`, но engine всегда
вызывает его без аргумента. Пользователь не может повысить budget.

Для корректной конечной модели больше 10 000 состояний общий verdict навсегда
будет INCONCLUSIVE, даже если explicit `AlwaysHolds(..., max_states=...)`
успешно завершится.

Нужен один явный policy source:

- `Spec(..., max_states=...)`;
- отдельный canonical verification config;
- либо CLI option, передаваемый в engine.

Canonical exploration также стоит переиспользовать для queries без собственного
initial: сейчас invariant verification и query phase независимо обходят один и
тот же graph.

### P2. Summary warnings не включает invariant/exploration warnings

Файлы:

- `src/analint/reporter/base.py:155`
- `src/analint/reporter/json_reporter.py:70`

`warning_count` по-прежнему считает только `structural_findings`.

Probe с `InvariantResult.NOT_CHECKED`:

```text
verdict: INCONCLUSIVE
invariant finding: WARNING not checked
summary.warnings: 0
```

Это не меняет fail-closed verdict, но JSON/terminal summary противоречит
показанным findings и `--strict` не видит такие warnings.

Нужно либо переименовать поле в `structural_warnings`, либо агрегировать warnings
из structural, scenario, query, invariant и exploration sections.

### P3. ROADMAP ошибочно обещает четырёхзначный общий verdict

Файлы:

- `ROADMAP.md:271`
- `src/analint/reporter/base.py:28`

ROADMAP говорит:

```text
verdicts различают PASS / FAIL / INCONCLUSIVE / NOT_CHECKED
```

Но `Verdict` остаётся трёхзначным:

```text
PASS / FAIL / INCONCLUSIVE
```

`NOT_CHECKED` — статус отдельного query/invariant, который агрегируется в общий
`INCONCLUSIVE`. Сам код и CLI здесь последовательны; исправить нужно формулировку
ROADMAP.

---

## Предыдущий review

Замечания `reviews/535ecb8-transition-kernel.md` закрыты:

- illegal initial + false pre + `Expect.FAIL` теперь FAIL;
- invariant evaluation error оставляет root witness без исходящих edges;
- transition/state ordering описан без противоречия;
- `tests/test_kernel.py` напрямую проверяет `TransitionResult`;
- `acting_user_is_active` добавлен к `assign_card` и `read_notification`;
- strict-xfail wording обновлён.

Focused probes:

```text
invalid invariant + false pre + Expect.FAIL:
  scenario passed = False

unevaluable invariant at root:
  states = 1
  edges = 0
  errors = 1
```

## Что сделано хорошо

- `Spec.initial` сохраняется через `_auto_populate`.
- Query без собственного source корректно использует canonical initial, а
  explicit source override работает.
- `InvariantResult` встроен в terminal, JSON, characterization и fail-closed
  aggregation.
- FAIL получает shortest trace к нарушающему состоянию.
- Cap даёт INCONCLUSIVE, невозможность построить root — NOT_CHECKED.
- Mafia теперь проверяет invariant под всеми допустимыми role assignments.
- Direct kernel tests закрывают общий blind spot agreement matrix.

## Проверка

```text
uv run pytest                 268 passed, 1 skipped
uv run ruff check .           passed
uv run ruff format --check .  passed
uv run ty check               passed
git diff --check              passed
```

Подтверждённые probes:

```text
broken transition during canonical verification:
  overall verdict -> PASS
  invariant -> PASS
  exploration findings -> empty

invalid unused Spec.initial:
  structural findings -> empty
  overall verdict -> PASS

event-dependent excluded action:
  invariant -> PASS
  completeness warning -> lost

InvariantResult.NOT_CHECKED warning:
  summary.warnings -> 0
```

## Рекомендуемый следующий commit

1. Сделать canonical verification возвращающей exploration artifact вместе с
   invariant results; не терять ERROR/WARNING/excluded.
2. Применить общий structural validator к `Spec.initial` и `query.initial`.
3. Определить policy для invariant status при excluded semantics.
4. Сделать canonical max_states настраиваемым и переиспользовать exploration
   между invariants и default-source queries.
5. Исправить warning aggregation и формулировку ROADMAP.

После этих изменений P1 можно считать закрытым.

---

## Resolution

Закрыто коммитом `578df8c` (14 июня 2026). Все находки воспроизведены пробами
до фикса:

- **P1#1** — `verify_invariants` теперь возвращает `(list[InvariantResult],
  Exploration | None)`; engine мёржит findings canonical exploration в
  `exploration_findings`. Broken action в canonical model даёт ERROR → общий
  verdict FAIL, а не зелёный invariant. Regression в `test_explorer`.
- **P1#2** — валидация `Initial` вынесена в общий `_validate_initial` и
  применяется к `query.initial` и `Spec.initial` (location `spec:<id>`),
  независимо от наличия queries/invariants. Regression в `test_explorer`.
- **P1#3** — invariant без контрпримера при непустом `exp.excluded` получает
  INCONCLUSIVE с findings, перечисляющим excluded actions (не PASS). Examples
  не затронуты (у них нет excluded actions). Regression в `test_explorer`.
- **P2#4** — добавлен `Spec.max_states` (сохраняется через `_auto_populate`),
  используется как бюджет canonical verification. Переиспользование одной
  exploration между invariants и default-source queries — отложенная
  оптимизация (корректности не касается).
- **P2#5** — `warning_count` агрегирует WARNING из structural, scenario, query,
  invariant и exploration секций; summary, `--strict` и показанные findings
  согласованы.
- **P3#6** — ROADMAP: статус проверки четырёхзначен, общий `Verdict`
  трёхзначен (NOT_CHECKED → INCONCLUSIVE).

Проверка: `uv run pytest` — 271 passed, 1 skipped; `ruff check`, `ruff format
--check`, `ty check` зелёные.

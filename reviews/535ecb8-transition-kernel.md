# Review: transition kernel after 3b8eb3d..535ecb8

Дата ревью: 14 июня 2026.

Коммиты:

```text
3b8eb3d Extract the transition kernel; route explorer through step()
8f8f0b4 Route scenario_runner through the transition kernel
9c98371 Freeze terminal entities against deletion in the kernel
a4cd0e9 Materialise emitted event payloads in the kernel
7ea5c96 Record the transition kernel in the roadmap
535ecb8 Treat an illegal initial state as a defect, not a rejection
```

Отдельный предшествующий `7b18b1c` с playable-spec experiment не входит в
объём этого review.

## Verdict

Архитектурное выделение kernel удачное: `scenario_runner` и `explorer`
действительно используют один `step()`, существенный объём дублированной
transition logic удалён, текущий suite и static checks зелёные.

Но утверждение ROADMAP «все расхождения закрыты» пока неверно. Обнаружены три
P1 semantic gaps и неполная миграция taskboard. Их следует закрыть до построения
Flow/simulation поверх kernel.

Статус:

> Kernel выделен, но его semantic contract ещё не полностью соблюдается.

---

## Findings

### P1. `Expect.FAIL` легитимизирует illegal initial state при ложном precondition

Файл:

- `src/analint/validator/scenario_runner.py:56`

После проверки pre-state invariants `step()` всё равно запускается. Для
`Expect.FAIL` итог определяется только так:

```python
passed = result.outcome is Outcome.REJECTED
```

Если initial state нарушает invariant, а precondition действия ложен, kernel
возвращает `REJECTED`, и сценарий ошибочно проходит, несмотря на
`pre_invariant_violated=True`.

Воспроизведение:

```text
scenario passed: True
ERROR: INVARIANT failed: X.n == 1
ERROR: PRE failed: X.done == True
INFO: correctly blocked — rules rejected this data as expected
```

Это прямо противоречит контракту коммита `535ecb8`: illegal initial state —
DEFECT, который `Expect.FAIL` не может легитимизировать.

Минимальное исправление:

```python
passed = result.outcome is Outcome.REJECTED and not pre_invariant_violated
```

Более строгий вариант: не вызывать `step()` вообще, если pre-state уже
нелегален. Добавить regression test на комбинацию:

```text
invalid initial invariant + false action pre + Expect.FAIL
```

### P1. Invariant evaluation error не останавливает explorer

Файл:

- `src/analint/validator/explorer.py:460`

В `_report_invariant_violations` ложный invariant выставляет
`violated = True`, но exception при `evaluate(...)` только записывает finding и
оставляет `violated=False`.

Поэтому root/successor с невычислимым invariant продолжает разворачиваться,
хотя это model defect.

Воспроизведение с:

```python
Invariant(X.n > "bad")
```

даёт:

```text
states: 2
edges: 2
ERROR: evaluation error ... [at: (initial state)]
ERROR: evaluation error ... [at: go]
```

Scenario для того же состояния корректно завершается DEFECT.

В `except` необходимо выставлять `violated = True`. Нужны отдельные тесты для:

1. evaluation error в initial root — root остаётся witness, исходящих рёбер нет;
2. evaluation error в successor — edge/state могут остаться witness, но state
   не разворачивается.

### P1. Фактический ordering не соответствует normative acceptance contract

Файлы:

- `tests/test_transition_conformance.py:15`
- `src/analint/validator/kernel.py:197`
- `src/analint/validator/scenario_runner.py:48`

Acceptance spec объявляет порядок:

```text
post -> post-state invariants -> emitted payload materialisation
```

Фактически `step()` материализует emitted payload до возврата, а post-state
invariants проверяются caller'ами только после успешного `step()`.

Комбинация:

```text
effect violates invariant
+ emitted payload evaluation error
```

даёт только emission error:

```text
scenario: emitted payload evaluation error
explorer: no edge, emitted payload evaluation error
post invariant violation: не проверен
```

Это также меняет заявленную witness-edge semantics: post-invariant defect должен
сохранять candidate edge/state, но ранний emission defect уничтожает этот
артефакт.

Нужно выбрать и зафиксировать один вариант:

1. изменить архитектуру фаз так, чтобы callers проверяли post-invariants до
   materialization emissions;
2. перенести invariant policy внутрь общей orchestration над kernel phases;
3. осознанно изменить normative ordering и witness contract.

Текущее состояние, когда документация и implementation расходятся, оставлять
не следует.

### P2. `TransitionResult` фактически не покрыт acceptance tests

Файлы:

- `src/analint/validator/kernel.py:63`
- `tests/test_transition_conformance.py`
- `src/analint/validator/scenario_runner.py:101`

Матрица декларирует contract:

```text
outcome, post_context, findings, emitted, changed_fields
```

Но тесты напрямую не вызывают `step()` и не проверяют:

- значения materialized event payload;
- `changed_fields` для Set/Add/Create/Delete;
- пустой diff effectless action;
- `entered`;
- findings/location для разных outcome.

Кроме того, `Emitted(...)` в scenario проверяется по
`scenario.action.emits`, а не по `TransitionResult.emitted`. Поэтому успешная
materialization payload не является наблюдаемой частью scenario acceptance
contract.

Добавить отдельные unit tests kernel API. Agreement scenario↔explorer не
заменяет проверку самого результата: два caller могут одинаково игнорировать
сломанное поле `TransitionResult`.

### P2. Миграция `examples/taskboard` неполная

Файлы:

- `examples/taskboard/actions.py:82`
- `examples/taskboard/actions.py:147`
- `examples/taskboard/invariants.py:17`

Комментарий утверждает:

```text
An inactive user cannot act.
```

`acting_user_is_active` добавлен к части user actions, но отсутствует минимум у:

- `assign_card` (`by=Member`);
- `read_notification` (`by=Member`).

Probe подтвердил: inactive `User` успешно выполняет `assign_card`.

Нужно либо добавить guard ко всем действиям, где `User` действительно является
actor, либо сузить формулировку политики. Для `assign_card` также следует
разделить acting membership и target assignee, если текущая singleton-модель
`Membership` смешивает эти роли.

### P3. ROADMAP содержит устаревшее описание strict-xfail gate

Файл:

- `ROADMAP.md:234`

ROADMAP одновременно говорит:

```text
normative strict-xfail ... XFAIL→XPASS
```

и ниже:

```text
test_transition_conformance — чистый agreement-spec без strict-xfail
```

После снятия последних marker первый пункт нужно переписать в прошедшем времени
или удалить.

---

## Что сделано хорошо

- Transition semantics действительно централизована в `validator/kernel.py`.
- `scenario_runner.py` существенно упростился и больше не содержит копию
  effects/Field/lifecycle logic.
- Explorer использует тот же `step()` и корректно не добавляет edges для
  transition-level DEFECT.
- Terminal `Delete`, lifecycle validation и pre/effect/post evaluation errors
  унифицированы.
- Emitted payload templates теперь реально материализуются.
- `TransitionResult` создаёт хорошую основу для Flow, simulation, trace и
  visualization.
- Исправление bogus world invariant в taskboard концептуально верное:
  активность actor — guard, а не утверждение, что все пользователи мира активны.

## Проверка

```text
uv run pytest                 251 passed, 1 skipped
uv run ruff check .           passed
uv run ruff format --check .  passed
uv run ty check               passed
git diff --check              passed
```

Focused probes подтвердили:

```text
invalid invariant + false pre + Expect.FAIL:
  scenario -> PASS (ошибка; должен быть DEFECT)

invariant evaluation error in explorer:
  root продолжает разворачиваться, создаются states/edges

post invariant + emission evaluation error:
  invariant не проверяется, emission error побеждает ordering

inactive taskboard user + assign_card:
  scenario -> PASS
```

## Рекомендуемый следующий commit

1. Исправить fail-closed обработку pre-state invariant в scenario.
2. Считать invariant evaluation exception нарушением в explorer.
3. Зафиксировать и реализовать единый ordering invariants/emissions.
4. Добавить прямые unit tests `step()`/`TransitionResult`.
5. Завершить или сузить taskboard active-user policy.
6. Обновить ROADMAP после снятия strict-xfail.

После этого kernel можно считать готовой базой для следующих фаз.

---

## Resolution

Закрыто коммитом `b8da3d6` (14 июня 2026). Оба P1-бага воспроизведены пробами
до фикса:

- **P1#1** — `scenario_runner`: `passed = REJECTED and not pre_invariant_violated`.
  Нелегальный initial state больше не легитимизируется `Expect.FAIL`, даже когда
  precondition тоже отклоняет действие. Regression в `tests/test_kernel.py`.
- **P1#2** — `explorer._report_invariant_violations`: `except` теперь ставит
  `violated=True`, так что невычислимый invariant оставляет state witness'ом без
  исходящих рёбер, как и в scenario. Regression в `tests/test_kernel.py`.
- **P1#3** — выбран вариант 3: семантика двухслойная и так и задокументирована
  (docstring kernel и conformance). `step` решает переход (… post → emitted),
  инварианты — предикат состояния, применяемый callers после. Witness-edge
  сохраняется только при state-level invariant violation; transition-level
  defect (включая нематериализуемый emission) кандидата не создаёт. Вердикт во
  всех случаях корректен — расходился лишь репортируемый дефект/witness.
- **P2#4** — `tests/test_kernel.py`: прямые unit-тесты `step()`/`TransitionResult`
  (outcome, post_context, changed_fields для Set/Add/Create/Delete, пустой diff
  effectless, entered, материализованный payload, bare-class passthrough).
- **P2#5** — `acting_user_is_active` добавлен к `assign_card` и
  `read_notification`; проба подтверждает, что неактивный User теперь не может
  выполнить `assign_card`. Singleton-модель: актор — это User-синглтон, поэтому
  guard достаточно; разделение acting-membership и assignee — отдельный, более
  глубокий рефактор модели, не входит в эту правку.
- **P3#6** — bullet про strict-xfail переписан в прошедшем времени.

Проверка: `uv run pytest` — 263 passed, 1 skipped; `ruff check` и `ty check`
зелёные. Taskboard snapshot перегенерирован (assign-card сценарии вернули
acting-user rule).

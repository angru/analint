# Review: kernel readiness after 50db26c..ca537a2

Дата ревью: 13 июня 2026.

Коммиты:

```text
50db26c Check Action.post for effectless actions too
1a1e64d Strengthen characterization oracle for the kernel refactor
594d8f2 Add semantic conformance matrix as the kernel acceptance gate
ca537a2 Use a dedicated fixture for the --strict consistency test
```

## Verdict

Коммиты качественные и закрывают непосредственные замечания прошлого review.
Но утверждение «pre-kernel gate готов» пока преждевременно.

Статус:

> Почти готово. До переноса transition logic нужен один небольшой commit,
> который превращает coarse agreement matrix в нормативный semantic contract.

Начинать обсуждать API `TransitionResult`/`step(...)` можно. Переносить в kernel
всю логику scenario/explorer до закрытия пунктов P1 ниже не следует.

---

## Findings

### P1. Conformance matrix принимает precondition evaluation error за обычный REJECTED

Файлы:

- `tests/test_transition_conformance.py:39`
- `src/analint/validator/scenario_runner.py:50`

`_scenario_cat` выводит категорию только из двух boolean `passed`. Сейчас
scenario с ошибкой вычисления precondition:

```python
pre=[Box.n > "bad"]
```

даёт:

```text
Expect.PASS -> false
Expect.FAIL -> true
category -> REJECTED
```

Explorer правильно создаёт `pre evaluation error`, то есть DEFECT.

Evaluation error не является правилом, которое корректно заблокировало action.
Kernel должен различать:

- false precondition → REJECTED;
- exception/type error while evaluating precondition → DEFECT.

Добавить strict-xfail acceptance test с ожидаемым DEFECT. Иначе kernel легко
закрепит текущий false-green `Expect.FAIL`.

### P1. Explorer adapter не распознаёт invariant defects

Файл: `tests/test_transition_conformance.py:52`.

`_explorer_cat` считает DEFECT только ERROR с location `action:<id>`. Ошибки
post-state invariant имеют location `invariant:<id>`, поэтому adapter видит
edge и возвращает ACCEPTED.

Воспроизведение:

```text
scenario: DEFECT
explorer: edge exists + invariant error
matrix adapter category: ACCEPTED
```

Нужны минимум два acceptance case:

1. invalid initial invariant → DEFECT, action не является «корректно rejected»;
2. post-effect invariant violation → DEFECT.

До kernel нужно решить, входит ли illegal successor в graph/result artifact.
Сейчас explorer добавляет state/edge до invariant check и только запрещает
дальнейшее expansion. Это наблюдаемая семантика, которую нельзя случайно
унаследовать без решения.

### P1. Terminal `Delete` принимается обоими путями, поэтому equality test его не ловит

Файлы:

- `src/analint/validator/scenario_runner.py:238`
- `src/analint/validator/explorer.py:500`
- `tests/test_transition_conformance.py:172`

Оба terminal guards строят `touched` только из `Set/Add/Subtract`. Удаление
present entity, находящейся в terminal lifecycle state, проходит:

```text
scenario -> ACCEPTED
explorer -> ACCEPTED
```

Это известная целевая delta в ROADMAP, но матрица проверяет только обычный
`Delete`, не terminal `Delete`.

Добавить strict-xfail с нормативным expected `REJECTED`. Простое совпадение
двух неправильных реализаций не является conformance.

### P1. Matrix сравнивает только coarse category, не transition result

Файл: `tests/test_transition_conformance.py`.

Research/20 требовал сравнивать:

- outcome;
- post-state;
- findings;
- emitted events;
- state diff.

Сейчас сравнивается только `ACCEPTED/REJECTED/DEFECT`. Две реализации могут
обе вернуть ACCEPTED, но записать разные значения полей или emissions.

Перед kernel зафиксировать минимальный будущий contract:

```text
TransitionResult
  outcome: ACCEPTED | REJECTED | DEFECT
  post_context
  findings
  emitted
  changed_fields / state diff
```

Не обязательно полностью реализовывать публичный API до refactor, но tests
должны проверять одинаковый post-state хотя бы для:

- simultaneous updates;
- saturation before postcondition;
- Create/Delete presence;
- effectless action.

### P1. Из известных semantic axes матрица покрывает только часть

Отсутствуют зафиксированные в research/20 случаи:

- pre evaluation error;
- effect evaluation error;
- post evaluation error;
- saturating Field;
- terminal Set и terminal Delete;
- pre/post invariant violation;
- emitted payload materialization;
- postcondition over deleted/absent entity.

Не каждый случай обязан быть отдельным большим fixture. Но semantics этих
ветвей должна быть решена до переноса, иначе kernel refactor одновременно
станет скрытым language-design change.

### P2. Characterization всё ещё не фиксирует traces/findings/completeness

Файлы:

- `tests/test_characterization.py`
- `tests/snapshots/examples.json`

State/edge hashes и per-scenario ids — существенное улучшение. Однако graph с
тем же state/edge multiset может получить:

- другой shortest trace из-за порядка expansion;
- исчезнувший model-defect finding;
- другой fired/excluded set;
- другую root attribution.

Для kernel достаточно добавить:

- query trace;
- normalized exploration/query findings;
- fired/excluded actions;
- root hash/count.

Полный state dump не нужен.

### P2. Strict warning scope из предыдущего review не исправлен

Файл: `src/analint/reporter/base.py:135`.

Dedicated fixture исправил качество test, но `warning_count` всё ещё считает
только structural warnings. Exploration/query/scenario warnings не влияют на
`--strict`.

Это не блокирует kernel, но не следует считать прошлый review закрытым
полностью.

---

## Что закрыто хорошо

- Effectless `Action.post` теперь действительно проверяется.
- Добавлены true/false effectless regression tests.
- Characterization фиксирует per-scenario status и форму graph, а не только
  число states.
- Snapshot regeneration явно объявлена review-only operation.
- Dedicated strict fixture больше не зависит от случайных warnings example.
- Known lifecycle divergence отмечена strict xfail.
- Текущий suite и static checks зелёные.

## Проверка

```text
uv run pytest        238 passed, 1 skipped, 1 xfailed
uv run ruff check .  passed
uv run ty check      passed
```

Дополнительные probes подтвердили:

```text
pre evaluation error:
  scenario -> REJECTED
  explorer -> DEFECT

post invariant violation:
  scenario -> DEFECT
  explorer adapter -> ACCEPTED

terminal Delete:
  scenario -> ACCEPTED
  explorer -> ACCEPTED
  target semantics -> REJECTED
```

## Минимальный readiness commit

1. Добавить normative strict-xfails для трёх cases выше.
2. Добавить saturation + effect/post evaluation error cases.
3. Сравнивать accepted post-state/state diff.
4. Зафиксировать `TransitionResult` outcome semantics и ordering.
5. Дополнить characterization trace/findings/excluded fingerprint.

После этого готовность к kernel можно подтвердить. Большой benchmark или
external GitHub policy model для начала refactor не нужны.

---

## Resolution

Закрыто следующим readiness commit:

- добавлены normative cases для pre evaluation error, initial/post invariant,
  terminal Set/Delete, effect/post evaluation errors и emitted payload;
- accepted branches сравнивают post-state для simultaneous effects, saturation
  и Create/Delete;
- graph semantics фиксирует наличие/отсутствие witness edge;
- characterization включает traces, findings, roots, fired/excluded и
  incompleteness;
- минимальный `TransitionResult` contract и ordering записаны в acceptance
  matrix.

Итоговый статус после этого commit: **готов к выделению transition kernel**.

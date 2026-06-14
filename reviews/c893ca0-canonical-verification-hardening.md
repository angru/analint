# Review: canonical verification hardening after 67be4f8

Дата ревью: 14 июня 2026.

Коммиты:

```text
578df8c Harden canonical invariant verification (review 67be4f8)
c893ca0 Record resolution of the canonical-verification review
```

## Verdict

Три основных дефекта из предыдущего review исправлены:

- transition defects из canonical exploration теперь влияют на общий verdict;
- foreign field в `Spec.initial.vary` даёт structural ERROR;
- excluded actions переводят invariant из PASS в INCONCLUSIVE.

ROADMAP и warning aggregation также исправлены. Переход к следующей работе не
заблокирован, но запись Resolution преждевременно объявляет `Spec.initial`
полностью валидируемым. Остались один false-green и три локальных дефекта
нового hardening-кода.

## Findings

### P1. Невычислимый `Spec.initial` всё ещё может дать общий PASS

Файлы:

- `src/analint/validator/structural.py:409`
- `src/analint/validator/structural.py:528`
- `src/analint/validator/engine.py:104`

Новый `_validate_initial()` проверяет только форму ссылок в `vary` и `where`.
Сам relation строится только если есть invariants или query без собственного
source. Поэтому canonical initial без потребителя по-прежнему может быть
семантически невалидным и не влиять на verdict.

Probe:

```python
class Box(Entity):
    n: int = Field(0, ge=0, le=1)

spec = Spec(
    id="s",
    name="S",
    entities=[Box],
    initial=Initial(
        vary=[Box.n],
        where=[Box.n != Box.n],
    ),
)
```

Фактический результат:

```text
structural findings: []
overall verdict: PASS
```

Но `build_initial_relation()` для этого же объекта возвращает
`Initial relation matches no states`.

Это тот же общий контракт, который был причиной P1#2: `Spec.initial` является
частью модели и должен быть валиден независимо от наличия invariants/queries.
Нужно один раз материализовать/проверить canonical relation после structural
validation и превратить ошибку построения в `spec:<id>` ERROR. Желательно
переиспользовать полученные roots в canonical verification и default-source
queries, чтобы не строить relation несколько раз.

Regression должен проверять end-to-end verdict для пустого relation и для
ошибки вычисления `where`, а не только foreign field reference.

### P2. `Initial.given` не входит в structural contract

Файл:

- `src/analint/validator/structural.py:528`

Общий helper вообще не проверяет `initial.given`. В результате незарегистрированная
entity принимается и реально попадает в canonical roots:

```python
class Registered(Entity):
    enabled: bool = False

class Foreign(Entity):
    enabled: bool = False

spec = Spec(
    id="s",
    name="S",
    entities=[Registered],
    initial=Initial(
        vary=[Registered.enabled],
        given=[Foreign()],
    ),
)
```

Фактический результат:

```text
structural findings: []
build error: None
root context keys: Foreign, Registered
```

Canonical graph не должен молча содержать entity вне `spec.entities`.
`_validate_initial()` должен валидировать snapshots так же строго, как scenario
givens: registered entity type, registered `InstanceRef`/Scope и отсутствие
дублирующихся context keys. Исправление автоматически относится и к
`query.initial`.

### P2. `Spec.max_states` принимает ноль и отрицательные значения

Файлы:

- `src/analint/models/root.py:59`
- `src/analint/validator/explorer.py:413`

Новая публичная настройка объявлена как обычный `int` без ограничения:

```text
Spec(..., max_states=0)  -> accepted
Spec(..., max_states=-1) -> accepted
```

Оба значения запускают exploration, сохраняют initial state и немедленно дают
INCONCLUSIVE с `states_explored=1`. Это выглядит как исчерпание корректного
budget, хотя конфигурация изначально невалидна.

Нужно задать положительное ограничение в модели, например
`Field(default=10_000, gt=0)`, и добавить model test. Аналогичный контракт стоит
отдельно распространить на query `max_states`, которые сейчас являются
dataclass-полями без runtime validation.

### P2. Merge exploration findings скрывает разные locations

Файл:

- `src/analint/validator/engine.py:96`

`_merge_exploration_findings()` дедуплицирует findings только по `message`.
Сам `Exploration.report_once()` корректно использует `(location, message)`, но
engine ослабляет ключ.

Два event-driven actions с одинаковой причиной exclusion дают два raw finding:

```text
action:a: excluded from exploration: ...
action:b: excluded from exploration: ...
```

После merge остаётся только `action:a`. Из-за этого reporter и
`warning_count` не отражают все показания explorer, несмотря на заявленный
контракт Resolution P2#5.

Ключ дедупликации должен включать минимум
`(severity, location, message)`. Добавить regression с двумя actions,
исключёнными по одной причине.

## Что сделано хорошо

- Broken canonical transition теперь даёт exploration ERROR и общий FAIL.
- Invariant над неполной transition relation больше не получает PASS.
- `warning_count` учитывает все result sections.
- `Spec.max_states` проходит через `_auto_populate`.
- Формулировка ROADMAP про общий трёхзначный verdict исправлена.
- Изменения локальны и не нарушили characterization suite.

## Проверка

```text
.venv/bin/pytest -q              271 passed, 1 skipped
.venv/bin/ruff check .           passed
.venv/bin/ruff format --check .  passed
.venv/bin/ty check               passed
git diff --check                 passed
```

Повторные probes прошлого review:

```text
broken canonical transition -> overall FAIL
foreign field in Spec.initial.vary -> structural ERROR / overall FAIL
excluded event action -> invariant INCONCLUSIVE
```

Итог: `578df8c` закрывает конкретные прошлые reproductions, но canonical
initial validation следует завершить до объявления соответствующего P1
полностью закрытым.

---

## Resolution

Закрыто коммитом `321ffdc` (14 июня 2026). Все четыре находки воспроизведены
пробами до фикса:

- **P1** — `build_canonical_initials(spec)` строит canonical relation один раз;
  engine валидирует построимость даже без consumers и превращает ошибку (пустой
  `where`, eval-error) в `spec:<id>` ERROR → общий FAIL. `verify_invariants`
  теперь принимает уже построенные `initials`, так что relation строится один
  раз и переиспользуется. End-to-end regression: пустой relation без
  invariants/queries → FAIL.
- **P2 (given)** — `_validate_initial` валидирует `initial.given` так же строго,
  как scenario givens: зарегистрированный тип, зарегистрированный
  InstanceRef/Scope, отсутствие дублей context key. Foreign entity больше не
  попадает в canonical roots молча. Применяется и к `query.initial`.
- **P2 (max_states)** — `Spec.max_states = Field(default=10_000, gt=0)`;
  неположительный бюджет отвергается как невалидная конфигурация (model test).
- **P2 (merge)** — `_merge_exploration_findings` дедуплицирует по
  `(severity, location, message)`, а не только по message; два действия,
  исключённых по одной причине, оба сохраняются. Regression на per-location.

Отложено (явно, не влияет на корректность): переиспользование одной canonical
exploration также и default-source queries — сейчас они строят свой initial
независимо.

Проверка: `uv run pytest` — 275 passed, 1 skipped; `ruff check`, `ruff format
--check`, `ty check` зелёные.

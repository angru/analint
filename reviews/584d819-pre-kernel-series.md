# Review: pre-kernel series 0dcb780..584d819

Дата ревью: 13 июня 2026.

Коммиты:

```text
0dcb780 Harden the verdict contract: fail-closed, strict-consistent, documented
25c2035 Explorer checks Action.post
584d819 Add characterization snapshot + indicative bench for examples
```

## Итог

Направление серии соответствует ROADMAP:

- verdict contract стал существенно безопаснее;
- capped exploration больше не выглядит зелёным;
- `--strict`, JSON и exit code согласованы для structural warnings;
- explorer начал проверять `Action.post`;
- перед kernel refactor появился deterministic characterization baseline;
- timing правильно не сделан CI gate.

Но переходить к kernel refactor без короткого follow-up рано. Есть два
блокирующих замечания:

1. effectless actions всё ещё обходят `Action.post`;
2. characterization snapshot не фиксирует сам transition graph и может
   пропустить существенный semantic drift.

---

## Findings

### P1. Effectless action по-прежнему не проверяет `Action.post`

Файл: `src/analint/validator/explorer.py:433`.

После enabledness explorer делает:

```python
if not action.effect:
    exp.edges.append((key, action.id, key))
    continue
```

`_check_post(...)` расположен ниже и никогда не вызывается для action без
effects.

Воспроизведение:

```python
class Box(Entity):
    n: int = 0

check = Action(id="check", post=[Box.n == 1])
```

Explorer принимает self-loop и не создаёт finding:

```text
query: PASS
edges: 1
findings: []
```

Это прямо противоречит заявлению коммита «Explorer checks Action.post» и
отметке ✅ в ROADMAP.

Рекомендация:

- строить post-context и выполнять общий post pipeline даже при пустом effect;
- добавить regression test на effectless action с true/false/error post;
- после появления transition kernel удалить отдельный fast path либо оставить
  его только после полного semantic step.

### P1. Characterization snapshot не является достаточным regression oracle для kernel

Файлы:

- `tests/test_characterization.py`
- `tests/snapshots/examples.json`

Snapshot фиксирует:

- общий verdict;
- только суммарное число passed/failed scenarios;
- warning count;
- query status и `states_explored`.

Он не фиксирует:

- scenario id → status/findings/rules;
- множество reachable states;
- edge multiset `source/action/target`;
- fired/excluded actions;
- exploration findings;
- shortest traces;
- roots и их rendered state;
- emitted events/post-state.

Два разных графа могут иметь одинаковые 216 states и те же query verdicts.
Даже два scenario могут поменяться результатами местами при прежнем суммарном
count. Поэтому формулировка «transition kernel must reproduce it» даёт
ложную уверенность.

Рекомендация перед kernel:

1. Сохранять per-scenario результаты по id.
2. Для каждого exploration сохранять normalized state set и edge multiset
   либо стабильные hashes от них.
3. Сохранять normalized findings и query traces.
4. Явно перечислить ожидаемые изменения baseline: lifecycle validation в
   scenario, terminal `Delete`, emitted payload и effectless post.
5. Snapshot остаётся characterization, а semantic conformance matrix является
   главным oracle.

### P1. `NOT_CHECKED` введён, но текущая incomplete semantics его не производит

Файлы:

- `src/analint/reporter/base.py`
- `src/analint/validator/explorer.py`
- `tests/test_soundness.py:180`

`NOT_CHECKED` корректно агрегируется в INCONCLUSIVE, но excluded event-driven
actions остаются warning + query PASS:

```text
handler: not assessed (excluded from exploration)
DeadActions: PASS
overall: PASS
```

Следовательно, fail-closed aggregation реализована, а fail-closed production
statuses — ещё нет. Это допустимо как промежуточный этап, но P0 нельзя считать
полностью закрытым.

Отдельно нужно согласовать терминологию: query status уже четырёхзначный, а
overall verdict намеренно трёхзначный и сворачивает `NOT_CHECKED` в
`INCONCLUSIVE`. ROADMAP сейчас говорит «verdicts различают ... NOT_CHECKED»,
что можно прочитать как требование к overall verdict.

Рекомендация:

- transition/exploration result должен нести completeness;
- property, область которой включает excluded semantics, возвращает
  `NOT_CHECKED` или `INCONCLUSIVE`;
- до этого PASS документировать как verdict только выполненной части.

### P2. `--strict` учитывает только structural warnings

Файл: `src/analint/reporter/base.py:135`.

`warning_count` считает только `structural_findings`. Warning в
`exploration_findings`, scenario/query findings не влияет на strict verdict.

Воспроизведение:

```text
exploration warning count: 0
effective_verdict(strict=True): PASS
```

Это уже наблюдаемо на excluded event semantics. Формулировка CLI
«Treat warnings as errors» шире фактической реализации.

Рекомендация:

- либо считать warnings во всех result channels;
- либо переименовать option/documentation в structural warnings only;
- добавить test на exploration warning.

### P2. Snapshot может законсервировать известные ошибки

Файл: `AGENTS.md`, раздел characterization snapshot.

Kernel должен не только сохранять поведение, но и намеренно устранить
расхождения scenario/explorer. Exact snapshot нельзя обновлять механически:
иначе semantic regression и ожидаемый fix выглядят одинаково.

Рекомендация:

- рядом со snapshot держать список ожидаемых delta;
- regeneration требует review diff;
- не использовать число states как автоматический признак корректности.

### P2. Текущий bench — smoke timing, не benchmark kernel

Файл: `scripts/bench.py`.

Максимальная модель имеет 216 states; остальные — 0–36. Измеренные времена:

```text
coin          216 states   ~61 ms
mafia         36 states    ~14 ms
fulfillment   34 states    ~4 ms
```

`best of 5` в одном процессе в основном даёт warm-cache timing. Это нормально
для ручного smoke comparison и честно описано в файле, но не отвечает на:

- scaling curve;
- memory/state;
- cost per state/edge;
- performance отдельных transition phases;
- момент, где появляется `INCONCLUSIVE`.

Не превращать этот script в gate. Для производительности нужен отдельный
parameterized synthetic benchmark (research/20).

### P3. Test на strict consistency может молча потерять coverage

Файл: `tests/test_verdict.py`.

Test делает `return`, если у taskboard больше нет warnings. После полезной
чистки example test станет зелёным без проверки strict semantics.

Рекомендация:

- создать минимальный fixture с гарантированным warning;
- не зависеть от incidental warning существующего example.

### P3. `reviews/` исключён из git

Файл: `.gitignore`.

Локальный handoff работает, и предыдущий агент его прочитал. Но review history
не попадает в commits и может потеряться. Если reviews являются частью
архитектурной памяти проекта, папку не следует игнорировать. Если это
намеренно временный канал, текущая настройка допустима.

Нужно принять явное решение, а не считать review одновременно записанным и
сохранённым в истории.

---

## Что сделано хорошо

- `0dcb780` устранил основные замечания прошлого review.
- Unknown query status теперь fail-closed.
- FAIL precedence и `NOT_CHECKED` покрыты тестами.
- JSON/terminal/CLI используют одну effective verdict policy.
- `25c2035` правильно считает false post model defect и отбрасывает edge.
- Benchmark timing не записан в brittle golden snapshot.
- Snapshot включает намеренно красные examples, а не только happy path.
- Полный test/static baseline зелёный.

## Проверка

```text
uv run pytest        225 passed, 1 skipped
uv run ruff check .  passed
uv run ty check      passed
```

Все текущие examples загружаются; `coin` и `trollbridge` ожидаемо остаются
красными.

## Рекомендуемый порядок до kernel

1. Исправить effectless-post bypass.
2. Добавить semantic conformance matrix для одного transition.
3. Усилить characterization per-scenario + graph/trace fingerprint.
4. Зафиксировать ожидаемые semantic delta.
5. После этого выделять общий transition kernel.

Большой внешний example не должен блокировать эти пять пунктов.

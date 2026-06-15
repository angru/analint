# Review: branch-protection evidence model

Дата ревью: 15 июня 2026.

Коммиты:

```text
373b46d Fix canonical invariant false-FAIL on absent slots
ad865bf P3 honesty pass: on/by/requires are documentary metadata
7386679 Record resolution of the presence/event-direction review
4465e16 Add the first external evidence model: GitHub branch protection
```

## Verdict

Исправление canonical presence выполнено правильно: теперь один
`invariant_is_applicable()` используется scenario/flow, explorer и canonical
invariant scanner.

Направление с отказом от немедленного event pool также правильное. Но новый
GitHub case пока нельзя считать завершённой внешней evidence-моделью:

- модель расходится с документированной GitHub semantics stale reviews;
- code-owner approval не считается обычным approval;
- отрицательные сценарии могут проходить не по заявленной причине;
- измерена одна правка, хотя evidence gate требует серию;
- основной `--what-if` loop на этой single-file модели не работает.

Это не аргумент возвращаться к event dispatch или менять kernel. Следующий шаг:
исправить fidelity и evidence harness этого кейса, затем сделать полный порт в
Quint/FizzBee. Вторую модель и новые примитивы пока начинать рано.

## Findings

### P1. Модель снимает blocking review обычным push

Файл:

- `examples/branch_protection/spec.py:108`

`push_commit` делает:

```python
Set(PullRequest.changes_requested, False)
```

GitHub документирует другое: blocking `Request changes` должен быть одобрен
автором review либо dismissed пользователем с соответствующими правами. Опция
`Dismiss stale pull request approvals` относится к approving reviews, а не к
автоматическому снятию request-changes.

Сейчас модель принимает трассу:

```text
request_changes
→ push_commit
→ approve
→ approve
→ code_owner_approve
→ checks_pass
→ merge
```

То есть push сам устраняет blocking review. Все queries остаются зелёными,
потому что к моменту merge поле уже ошибочно очищено.

Исправление:

- `push_commit` не должен менять `changes_requested`;
- действие лучше назвать `dismiss_changes_request` или
  `approve_after_changes`, а не смешивать «resolved / dismissed»;
- добавить executable Flow: request changes → push → approvals/checks →
  merge должен быть blocked до явного dismiss/approve.

### P1. Base update сохраняет stale approvals

Файлы:

- `examples/branch_protection/spec.py:132`
- `examples/branch_protection/spec.py:138`

Модель заявляет, что stale-review dismissal включён, но `base_advanced` и
`update_branch` не сбрасывают `approvals`/`code_owner_approved`.

GitHub docs прямо указывают, что approving review становится stale, когда diff
меняется, включая Update branch и изменения merge base.

Подтверждённая моделью трасса:

```text
approve
→ approve
→ code_owner_approve
→ checks_pass
→ base_advanced
→ update_branch
→ checks_pass
→ merge
```

Она принимается без повторных approvals.

Нужно явно выбрать одну конфигурацию:

```text
required approvals = 2
dismiss stale approvals = enabled
require code owner = enabled
strict status checks = enabled
bypass = disabled
```

и сбрасывать review state в том переходе, где модель считает diff/merge-base
изменившимся. После этого закрепить Flow с обязательным re-review.

Официальный источник:

<https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches>

### P1. Code-owner approval ошибочно не входит в общее число approvals

Файл:

- `examples/branch_protection/spec.py:89`

`code_owner_approve` устанавливает только boolean. Поэтому witness требует:

```text
approve → approve → code_owner_approve
```

то есть три approvals при `REQUIRED_APPROVALS = 2`.

В GitHub code-owner approval является approving review. Отсюда следует
(это inference из общей review semantics и code-owner requirement), что он
может одновременно удовлетворять общему required count и code-owner
requirement. Для политики «два approvals, один из них code owner» достаточно
двух review.

Не обязательно вводить reviewer identities. Bounded abstraction может хранить:

```text
ordinary_approvals: 0..2
code_owner_approved: bool
```

а policy выразить как:

```text
code_owner_approved
AND (ordinary_approvals >= 2
     OR (code_owner_approved AND ordinary_approvals >= 1))
```

Лучше подобрать название поля, ясно показывающее, входит ли code-owner review
в count. Текущая пара полей двусмысленна.

### P1. Отрицательные merge-сценарии дают false confidence

Файл:

- `examples/branch_protection/spec.py:173`

Три сценария не изолируют проверяемое условие:

```text
sc_merge_underapproved
sc_merge_failing_checks
sc_merge_behind_base
```

Во всех `code_owner_approved` остаётся `False`. Поэтому каждый сценарий
останется PASS даже при случайном удалении своей целевой merge-проверки.

Для single-fault negative scenario все остальные условия должны быть зелёными:

```python
PullRequest(
    approvals=2,
    checks=Checks.PASSING,
    behind_base=False,
    changes_requested=False,
    code_owner_approved=True,
)
```

и меняться должно только одно целевое поле. Также отсутствуют аналогичные
сценарии для `changes_requested=True` и отсутствующего code-owner approval.

Queries полезнее сценариев для полного graph, но они не отменяют false-positive
characterization tests: snapshot сейчас закрепляет только статус PASS, а не
причину rejection.

### P1. Honesty-pass не дошёл до agent-facing API

Файлы:

- `src/analint/query.py:434`
- `src/analint/mcp_server.py:74`
- `tests/test_query.py:74`
- `README.md:346`

После решения «`on` — documentary metadata» публичный JSON всё ещё возвращает:

```json
{"triggers_downstream": [...]}
```

MCP tool обещает показать actions, которые исходный action “triggers
downstream”, а тест закрепляет это имя. Для агента это более сильный контракт,
чем docstring, и он прямо противоречит новой семантике.

README также продолжает описывать `Actor` как “Who can trigger an action”, хотя
`by` не является authorization/enabledness guard.

Рекомендуемые имена:

```text
documented_handlers
listed_in_on
handled_by_metadata
```

Если JSON compatibility уже считается публичной, старый ключ можно оставить
на один цикл как deprecated alias. До этого ROADMAP не должен говорить, что
формулировки без trigger semantics закрыты полностью.

### P1. `--what-if` gap нельзя считать «мелочью»

Файлы:

- `research/23-evidence-github-branch-protection.md:56`
- `src/analint/validator/engine.py:21`
- `src/analint/loader/python_loader.py:64`

Проба подтверждает:

```text
analint check examples/branch_protection --what-if patch.py
LOAD ERROR: No module named 'branch_protection'
exit 3
```

Single-file entry импортируется под synthetic name, который patch не может
стабильно знать. При этом:

- README обещает `--what-if` без package-only оговорки;
- agent loop делает what-if центральным шагом;
- большинство примеров single-file;
- новый evidence case оценивает agent workflow, но не может пройти его основной
  цикл.

Это не cosmetic issue. Его стоит исправить до продолжения evidence gate.
Временное добавление `__init__.py` к одному примеру скроет проблему, но не
исправит контракт. Нужен стабильный способ patch импортировать уже загруженную
single-file spec: документированный alias/namespace либо loader API, не
зависящий от synthetic module name.

### P2. Evidence gate отмечен выполненным раньше собственного критерия

Файлы:

- `ROADMAP.md:327`
- `research/23-evidence-github-branch-protection.md:30`

ROADMAP требовал «несколько последовательных изменений требований». Проведено
одно: code-owner approval. Это полезная первая итерация, но не серия.

Кроме того, изменение и проверяющий query добавлены одновременно. Эксперимент
показывает локальность diff и пересчёт witness, но пока слабо проверяет:

- удаление/ослабление правила;
- изменение transition semantics;
- cross-cutting изменение нескольких actions;
- mutation sensitivity существующих properties;
- качество review diff между analint и baseline.

Пункт следует вернуть в `in progress`. Минимальная серия для этого case:

1. включить/выключить stale-review dismissal;
2. переключить strict checks на loose;
3. добавить “latest push approved by someone else”;
4. добавить bypass actor либо явно зафиксировать bypass disabled.

Не все варианты обязаны остаться в итоговой модели: важен сохранённый diff и
измерение стоимости каждой правки.

### P2. Формулировка «events не нужны» шире полученного evidence

Файлы:

- `research/23-evidence-github-branch-protection.md:82`
- `ROADMAP.md:330`

Один агрегированный `PullRequest` показывает только:

> Для выбранной абстракции одной PR policy event state не понадобился.

Он не доказывает, что events не нужны для:

- нескольких PR и merge queue;
- asynchronous delivery/retry;
- audit subscribers;
- correlation между CI run и конкретным head SHA;
- at-least-once/exactly-once properties.

Разворот research/22 всё равно остаётся правильным: кейс не дал основания
добавлять event pool. Но формулировку следует ослабить с «подтверждает» до
«не опровергает; demand не обнаружен в этом case».

### P2. Research не содержит source/assumption matrix

Файл:

- `research/23-evidence-github-branch-protection.md`

Для внешней модели нужна трассируемость между реальной системой и abstraction.
Сейчас нет ссылок на GitHub docs и не отделены:

- реальные правила;
- выбранные optional settings;
- намеренные упрощения;
- свойства, которые модель не покрывает.

Без этого зелёный verifier доказывает согласованность модели с самой собой, но
не fidelity к GitHub.

Добавить таблицу:

```text
GitHub rule | source | modeled field/action | assumption/omission | property
```

Это важнее увеличения числа examples.

## Что сделано хорошо

- Presence fix закрыт единым helper, без третьей локальной копии алгоритма.
- Event pool не начали реализовывать после обнаруженных design blockers.
- Branch-protection case bounded и достаточно мал для exhaustive BFS.
- Policy разложена на независимые `Unreachable` queries, а достижимость merge
  проверена отдельным witness.
- Research честно говорит, что Quint/FizzBee пока не портированы.
- Обнаруженный `--what-if` gap записан, а не скрыт.

## Рекомендуемый путь

```text
P0  исправить fidelity branch_protection + isolated scenarios/Flows
P1  исправить single-file --what-if
P1  завершить honesty-pass в JSON/MCP/README
P2  добавить source/assumption matrix и mutation/change series
P3  портировать тот же case в Quint (или FizzBee) и сравнить реальные diffs
P4  только затем выбрать вторую внешнюю модель
P5  новые DSL primitives — только из повторившейся evidence-боли
```

Для второй модели позже следует выбрать case, который нагружает не ещё одну
single-entity policy, а composition + bounded multiplicity + несколько
экземпляров. Иначе evidence будет повторять сильную сторону текущего engine,
не проверяя его границы.

## Проверка

```text
uv run pytest -q              289 passed, 1 skipped
uv run ruff check .           passed
uv run ruff format --check .  passed
uv run ty check               passed
analint branch_protection     14 scenarios, 7 queries, 1 invariant PASS
```

Целевые probes:

```text
request_changes → push_commit → ... → merge          ACCEPTED (model bug)
approve×2 → code-owner → base/update → ... → merge   ACCEPTED (model bug)
single-file --what-if import                          exit 3
```

---

## Resolution

Принято почти полностью. Все P1 и оба содержательных P2 закрыты в рабочем дереве
(коммит — после approval). Фиксы воспроизведены пробами/тестами до и после.

### Fidelity модели (P1×3)

- **push снимал blocking review** — `push_commit` больше НЕ трогает
  `changes_requested`. Снять blocking review можно только явным
  `dismiss_changes_request`. Свидетель — `flow_changes_request_blocks_until_dismissed`
  (request → push → review всё ещё блокирует → dismiss → approve×2 → merge) и
  `sc_push_keeps_changes_requested`.
- **base update сохранял stale approvals** — принято с уточнением: новый head-коммит
  сбрасывает approvals, а движение base — нет. Поэтому `update_branch` (merge base
  в head = новый коммит) теперь сбрасывает `approvals`+`code_owner_approved`+checks,
  а `base_advanced` (head не меняется) только ставит `behind_base`. Свидетель —
  `flow_push_forces_reapproval`, `sc_update_branch`, `sc_base_advanced`.
- **code-owner не входил в approvals** — теперь code-owner review ЕСТЬ approving
  review: `code_owner_approve` инкрементит `approvals` и ставит флаг. Политике
  хватает двух review (один — code owner), witness стал
  `approve → checks_pass → code_owner_approve → merge` (был три review). Добавлен
  инвариант soundness `code_owner_is_an_approval`.

### Сценарии (P1)

Негативы переписаны single-fault: общий all-green baseline `_ALL_GREEN`, в каждом
меняется ровно одно целевое поле. Добавлены недостающие
`sc_merge_with_changes_requested` и `sc_merge_without_code_owner`. (Главный
mutation-детектор всё же не сценарии, а `never_merge_*`: каждый падает при удалении
своего конъюнкта из `mergeable`.)

### Honesty-pass в agent-facing API (P1)

`affects` JSON: `triggers_downstream` → `documented_handlers` (+ комментарий, что
`on` documentary, не dispatch). MCP-описание `affects` переформулировано. README
`Actor` переписан (documentary, не authz). Тест переименован
`test_affects_action_shows_documented_handlers`. ROADMAP P3 отмечает закрытие
API-поверхности.

### single-file `--what-if` (P1)

Причина: single-file spec грузится под синтетическим именем, патч его не знает.
Фикс: загруженный entry-модуль регистрируется под стабильным алиасом
`analint_spec` (`engine._register_spec_alias`) перед импортом патча. Патч всегда
делает `from analint_spec import ...` независимо от раскладки. Документировано в
README; регрессия `test_what_if_patch_on_single_file_spec` (cloak). НЕ через
`__init__.py`-костыль.

### Evidence gate откатан в in-progress (P2)

ROADMAP: «серия изменений» = пока ОДНА правка, не серия; gate → ⏳. Формулировка
«события не нужны» ослаблена до «demand в этой абстракции не обнаружен; не
опровергает разворот, но multi-PR/merge-queue/async не покрыты». Вторая модель
должна бить по composition + multiplicity.

### Matrix + граница выразительности (P2)

В research/23 добавлена source/assumption matrix (GitHub rule → поле/действие →
упрощение → property, со ссылкой на GitHub docs) и честная заметка: «changes
addressed» / «stale review» — path/temporal свойства, которые analint
(только reachability) строго выразить не может; гарантия здесь структурная (один
clearer + guard + Flow-свидетель). Это ровно то место, где Quint/FizzBee сильнее.

### Что НЕ сделано (по плану ревью — отдельные крупные шаги)

- Полный порт кейса в Quint/FizzBee + замер на серии изменений.
- Серия из нескольких изменений требований (вкл/выкл правил, strict→loose, cross-cutting).
- Вторая внешняя модель (composition / multiplicity).

Модель: 121 reachable state (было 145), всё зелёное; 18 scenarios, 2 flows,
7 queries, 2 invariants.

Проверка: `uv run pytest` — 291 passed, 1 skipped; `ruff check`,
`ruff format --check`, `ty check` зелёные. Пробы:
`analint check examples/branch_protection --what-if /tmp/patch.py` (single-file) → exit 0;
single-fault негативы PASS строго по своему правилу.

---

## Follow-up review

The resolution addressed the original findings, but a second pass found two
remaining implementation gaps before commit:

1. `code_owner_approve` still required `approvals < 2`. A PR with two ordinary
   approvals could therefore never receive the required code-owner approval.
   The approval count is now explicitly threshold-capped with
   `saturate=True`, and a code owner may approve at the threshold while the
   count remains two. `sc_code_owner_can_approve_after_threshold` covers this
   valid review order.
2. `analint_spec` was left permanently in `sys.modules`, leaking one validated
   spec into later validations in a long-lived MCP process. The alias is now
   scoped to patch execution and restores any previous module. What-if patches
   are also re-executed on every validation, so editing a patch at the same path
   is visible to the next MCP check.

The working-language policy is now recorded in `AGENTS.md`: user prompts may be
Russian, but agent replies and all newly authored repository content are
English.

Final verification:

```text
uv run pytest -q              291 passed, 1 skipped
uv run ruff check .           passed
uv run ruff format --check .  passed
uv run ty check               passed
branch_protection             18 scenarios, 2 flows, 7 queries, 2 invariants PASS
```

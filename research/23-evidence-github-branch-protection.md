# Evidence: GitHub branch-protection policy as an analint model

Дата: 15 июня 2026.

Первый внешний change-oriented кейс из ROADMAP evidence-gate (research/20).
Модель: `examples/branch_protection/` — GitHub protected-branch / required
pull-request policy. Реальная система, не придуманная под analint.

## Что верифицировано

Один bounded `PullRequest` (state-lifecycle OPEN→MERGED/CLOSED, approvals 0..2,
changes_requested, checks PENDING/PASSING/FAILING, behind_base, code_owner_approved)
+ действия review/CI/base/merge/close. Политика merge — один именованный
предикат `mergeable`. 145 reachable states.

Ценность — не «нашли баг» (политика корректна), а **доказанная
небайпасабельность по всем порядкам действий**:

- `merge_is_achievable` (Reachable) — happy-path существует; witness:
  `approve → approve → checks_pass → code_owner_approve → merge`.
- `never_merge_underapproved/failing/with_changes/behind/without_code_owner`
  (Unreachable) — merge никогда не обходит ни один пункт политики, при любом
  чередовании push (сбрасывает stale approvals), base_advanced, checks и т.д.
- `merged_satisfied_policy` (Invariant, авто-проверка по reachable states) —
  каждое merged-состояние удовлетворяет политике.

Это то, что нельзя получить сценариями: сценарии проверяют «придуманные» пути,
queries — все 145.

## Change-cost эксперимент

Изменение требования «require code-owner approval» (реальная настройка GitHub):
**~6 строк модели** — поле `code_owner_approved`, конъюнкт в `mergeable`,
действие `code_owner_approve`, сброс при `push_commit`, query
`never_merge_without_code_owner`.

Эффект сразу при `check`:

- **сломался `sc_merge_happy`** — существующий happy-path больше не мёржится без
  code-owner approval. analint поймал регрессию от изменения требований (правка
  сценария — 1 строка).
- `merge_is_achievable` пересчитал witness, добавив `code_owner_approve` —
  движок сам вывел новый обязательный шаг.
- state space 73 → 145.

Вывод: изменение локализовано (политика — один предикат `mergeable`), а
верификатор немедленно показал и новый требуемый путь, и сломанный существующий
пример. `affects PullRequest.approvals` до правки даёт точный радиус удара
(written_by: approve, push_commit; read_by: approve, merge; invariants;
scenarios) — агент видит, что заденет, не открывая файлы.

## Agent surface (измерено)

- `affects <field>` — точный кросс-референс read/write/invariants/scenarios. Полезно.
- `show action/lifecycle` — структурированный pre/effect/переходы. Полезно.
- `--what-if <patch>` — **находка**: работает только если spec импортируется как
  пакет (taskboard с `__init__.py`), а single-file пример (`spec.py` без
  `__init__.py`, как coin/cloak/branch_protection) патч импортировать не может
  (`No module named 'branch_protection'`). Нужно либо документировать требование
  «пакет», либо дать патчу способ ссылаться на уже загруженный модуль.

## Сравнение с Quint / FizzBee (честно: структурное, не полный порт)

Оба моделируют это как transition system с инвариантами — концептуально то же,
что analint BFS + Unreachable/AlwaysHolds. Различия:

- **Читаемость**: в analint действия (`approve`, `push_commit`, `merge`) и есть
  доменные переходы, а `mergeable` читается как сама политика. Quint/FizzBee —
  `action`/`step` с `any {...}` и guard-выражениями; ближе к коду TLA-стиля.
- **Выразительность/инструменты в пользу Quint/FizzBee**: темпоральные свойства
  (не только reachability), fairness, рандомизированная симуляция, Apalache
  (SMT), заметно больший масштаб. analint — только bounded BFS + reachability-
  классы.
- **В пользу analint для этой ниши**: `show`/`affects`/`--what-if`,
  авто-инвариант по canonical model, scenario-coverage warnings,
  spec-as-checkable-doc на Python без отдельного языка.

Честный вердикт: для **change-oriented доменной политики** analint конкурентен и
заметно доменно-читаемее; **не доказано «лучше»** без полного порта в Quint и
сравнения authoring-time/найденных дефектов на серии изменений. Это остаётся.

## Нужны ли события? Нет.

Домен PR review/CI/merge выглядит «событийным» (approve, push, checks, base
moved), но смоделировался **полностью через состояние** (status-поля), без
operational `on`/event-pool. Это прямое подтверждение разворота research/22:
state-chaining (ядро проекта) достаточно для реального event-ish домена;
operational `on` не понадобился.

## Статус evidence-gate

- ✅ одна внешняя change-oriented модель (эта).
- ⏳ вторая внешняя модель.
- ⏳ полный порт того же кейса в Quint/FizzBee + замер authoring/diff/дефектов на
  серии изменений (сейчас — структурное сравнение).
- ⏳ мелочь: `--what-if` для single-file specs; опциональный `NoDeadEnd(goal=merged)`
  честно отметит, что `close` — терминальный тупик для merge (ожидаемо).

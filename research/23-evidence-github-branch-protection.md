# Evidence: GitHub branch-protection policy as an analint model

Дата: 15 июня 2026 (ревизия после ревью `reviews/4465e16-branch-protection-evidence.md`).

Первый внешний change-oriented кейс из ROADMAP evidence-gate (research/20).
Модель: `examples/branch_protection/` — GitHub protected-branch / required
pull-request policy. Реальная система, не придуманная под analint.

## Что верифицировано

Один bounded `PullRequest` (state-lifecycle OPEN→MERGED/CLOSED, approvals 0..2,
code_owner_approved, changes_requested, checks PENDING/PASSING/FAILING,
behind_base) + действия review/CI/base/merge/close. Политика merge — один
именованный предикат `mergeable`. **121 reachable state.**

Ценность — не «нашли баг» (политика корректна), а **доказанная
небайпасабельность по всем порядкам действий**:

- `merge_is_achievable` (Reachable) — happy-path существует; witness:
  `approve → checks_pass → code_owner_approve → merge` (два review, один из них —
  code owner).
- `never_merge_underapproved/without_code_owner/failing/with_changes/behind`
  (Unreachable) — merge никогда не обходит ни один пункт политики, при любом
  чередовании push (сбрасывает stale approvals), base_advanced, update_branch,
  checks и т.д. **Каждый `never_merge_*` — это и есть mutation-детектор своего
  правила**: убери конъюнкт из `mergeable` — соответствующий запрос станет FAIL.
- `merged_satisfied_policy` (Invariant, авто-проверка по reachable states) —
  каждое merged-состояние удовлетворяет политике.
- `code_owner_is_an_approval` (Invariant) — soundness абстракции: флаг
  code-owner не может стоять без хотя бы одного approval за ним.

Это то, что нельзя получить сценариями: сценарии проверяют «придуманные» пути,
queries — все 121.

## Source / assumption matrix

Трассируемость «реальная система → абстракция». Источник:
GitHub Docs, *About protected branches* /
*About protected branches → Require pull request reviews*
(<https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches>).

| GitHub rule | modeled field / action | assumption / omission | property |
|---|---|---|---|
| Require N approving reviews | `approvals: 0..2`, `approve` | N=2; threshold-capped (`saturate=True`), reviewers без идентичности | `never_merge_underapproved` |
| Require review from Code Owners | `code_owner_approved`, `code_owner_approve` | code-owner review **считается** одним approval (counts toward total) | `never_merge_without_code_owner`, `code_owner_is_an_approval` |
| Dismiss stale approvals on new commit | `push_commit`, `update_branch` сбрасывают `approvals`+`code_owner_approved` | «новый коммит» = push **или** update-from-base (merge base в head) | `flow_push_forces_reapproval` |
| «Changes requested» блокирует merge | `changes_requested`, `request_changes`, `dismiss_changes_request` | push **не** снимает blocking review — только явный dismiss/re-review | `never_merge_with_changes`, `flow_changes_request_blocks_until_dismissed` |
| Require status checks to pass | `checks: pending/passing/failing`, `checks_pass/fail` | один агрегированный статус, не набор отдельных checks | `never_merge_failing` |
| Require branches up to date (strict) | `behind_base`, `base_advanced`, `update_branch` | base двигается → PR behind; head не меняется, approvals целы | `never_merge_behind` |
| Merge только при выполнении политики | `merge` (pre=`mergeable`) | terminal MERGED/CLOSED заморожены | `merged_satisfied_policy`, `policy_always_holds` |
| Allow bypass / admin override | — | **намеренно опущено** (bypass disabled) | — |

Намеренные упрощения / что модель НЕ покрывает: несколько PR и merge queue;
идентичности ревьюверов («последний push одобрен кем-то другим»); привязка CI к
конкретному head SHA; admin bypass; асинхронная доставка/ретраи.

### Граница выразительности (честно)

«Changes requested addressed» и «stale review dismissed» — это **path/history**
свойства («ранее запросили изменения; были ли они сняты явно?»). У analint есть
только reachability над состоянием, не темпоральные свойства. Поэтому
`never_merge_with_changes` строго говоря доказывает лишь, что в момент merge флаг
снят — **не** что запрошенные изменения были адресованы. Гарантия здесь
структурная: `dismiss_changes_request` — единственный, кто снимает флаг, а push
его не трогает; `flow_changes_request_blocks_until_dismissed` — исполняемый
свидетель обязательного явного dismiss. Это ровно тот случай, где Quint/FizzBee с
их темпоральными свойствами строго сильнее — и это надо проверить портом.

## Change-cost (одна правка измерена; серия — ещё нет)

Изменение требования «require code-owner approval» (реальная настройка GitHub):
**~6 строк модели** — поле `code_owner_approved`, конъюнкт в `mergeable`,
действие `code_owner_approve`, сброс при `push_commit`/`update_branch`, query
`never_merge_without_code_owner`.

Эффект сразу при `check`:

- **сломался `sc_merge_happy`** — happy-path больше не мёржится без code-owner
  approval; analint поймал регрессию от изменения требований.
- `merge_is_achievable` пересчитал witness, добавив code-owner шаг — движок сам
  вывел новый обязательный путь.

Вывод: изменение локализовано (политика — один предикат `mergeable`), а
верификатор немедленно показал и новый требуемый путь, и сломанный пример.
`affects PullRequest.approvals` до правки даёт точный радиус удара (writers,
readers, инварианты, сценарии) — агент видит, что заденет, не открывая файлы.

**Это одна итерация, а не серия.** Evidence-gate требует несколько
последовательных изменений требований (и измерение diff каждого). Минимальная
серия для этого кейса: вкл/выкл dismiss-stale-on-push; strict→loose checks;
«последний push одобрен другим ревьювером»; bypass actor (или явно bypass
disabled). Это остаётся (gate → in progress).

## Agent surface (измерено)

- `affects <field>` — точный кросс-референс read/write/invariants/scenarios. Полезно.
- `show action/lifecycle` — структурированный pre/effect/переходы. Полезно.
- `--what-if <patch>` — **починено**. Раньше single-file spec (`spec.py` без
  `__init__.py`, как coin/cloak/branch_protection) грузился под синтетическим
  именем, и патч не мог его импортировать (`No module named ...`). Теперь
  загруженная spec всегда доступна патчу под стабильным алиасом `analint_spec`
  (`from analint_spec import PullRequest`), независимо от раскладки. Проверено
  CLI и регрессионным тестом `test_what_if_patch_on_single_file_spec`.

## Сравнение с Quint / FizzBee (честно: структурное, не полный порт)

Оба моделируют это как transition system с инвариантами — концептуально то же,
что analint BFS + Unreachable/AlwaysHolds. Различия:

- **Читаемость**: в analint действия (`approve`, `push_commit`, `merge`) и есть
  доменные переходы, а `mergeable` читается как сама политика. Quint/FizzBee —
  `action`/`step` с `any {...}` и guard-выражениями; ближе к коду TLA-стиля.
- **Выразительность/инструменты в пользу Quint/FizzBee**: темпоральные свойства
  (не только reachability — см. границу выше про path-свойства), fairness,
  рандомизированная симуляция, Apalache (SMT), заметно больший масштаб. analint
  — только bounded BFS + reachability-классы.
- **В пользу analint для этой ниши**: `show`/`affects`/`--what-if`,
  авто-инвариант по canonical model, scenario-coverage warnings,
  spec-as-checkable-doc на Python без отдельного языка.

Честный вердикт: для **change-oriented доменной политики** analint конкурентен и
заметно доменно-читаемее; **не доказано «лучше»** без полного порта в Quint и
сравнения authoring-time/найденных дефектов на серии изменений. Это остаётся.

## Нужны ли события? Demand в этом кейсе не обнаружен.

Домен PR review/CI/merge выглядит «событийным» (approve, push, checks, base
moved), но в **выбранной абстракции одной агрегированной PR-политики**
смоделировался полностью через состояние (status-поля), без operational
`on`/event-pool. Это **не опровергает** разворот research/22 и не дал ни одного
повода добавлять event pool.

Но это и **не доказывает**, что события не нужны вообще: один агрегированный
`PullRequest` ничего не говорит про несколько PR / merge queue, асинхронную
доставку с ретраями, audit-subscribers, корреляцию CI-run ↔ head SHA,
at-least-once/exactly-once. Эти нагрузки — задача для второй модели (она должна
бить по composition + bounded multiplicity, а не повторять сильную сторону
текущего движка).

## Статус evidence-gate

- ⏳ две внешние модели — **1 из 2** (эта; вторая должна нагружать composition /
  несколько экземпляров).
- ⏳ полный порт того же кейса в Quint/FizzBee + замер authoring/diff/дефектов на
  **серии** изменений (сейчас — структурное сравнение + одна измеренная правка).
- ⏳ серия изменений требований (вкл/выкл правил, strict→loose, cross-cutting) с
  сохранёнными diff и стоимостью каждой правки.
- ✅ single-file `--what-if` починен (стабильный алиас `analint_spec`).
- ✅ source/assumption matrix добавлена (трассируемость к GitHub docs).

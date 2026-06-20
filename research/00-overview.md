# Исследование: analint за пределами аналитики

Вопрос: насколько текущий DSL пригоден для описания **систем вообще** — включая
игры, сюжеты, симуляции — и нужно ли его перерабатывать.

## Файлы

| Файл | Содержание |
|---|---|
| [01-expressiveness.md](01-expressiveness.md) | Формальная характеристика текущего DSL: что он умеет, где жёсткие пределы |
| [02-related-work.md](02-related-work.md) | Сравнение с TLA+/Alloy, PDDL, statecharts, Ceptre, ink, Machinations |
| [03-games-narrative-simulation.md](03-games-narrative-simulation.md) | Разбор применимости к сюжетам, играм и симуляциям, с примерами |
| [04-direction.md](04-direction.md) | Вердикт и рекомендации: что менять, что оставить, что не делать |
| [05-universal-dsl.md](05-universal-dsl.md) | Универсальный словарь: 8 примитивов вместо 23, принципы читаемости, миграция |
| [06-case-study-cloak-of-darkness.md](06-case-study-cloak-of-darkness.md) | Кейс-стади: Cloak of Darkness и «Тролий мост» целиком на DSL, найденные дыры |
| [07-declarative-semantics.md](07-declarative-semantics.md) | Чистая декларативность: эффекты как факты (не команды), параметризация событий |
| [08-ai-agents.md](08-ai-agents.md) | analint для AI-агентов: ландшафт 2026, инверсия экономики, интерфейс, вердикт |
| [09-loader-and-entrypoint.md](09-loader-and-entrypoint.md) | Лоадер: подтверждённый баг двойного импорта, переход на точку входа + реестр |
| [10-scale-and-honest-assessment.md](10-scale-and-honest-assessment.md) | После v1.0: впечатления агента-пользователя, пределы синглтонов, что нужно до реальных продуктов |
| [11-spec-code-bridge.md](11-spec-code-bridge.md) | Мост спека↔код: якоря @implements отклонены; пин + семантика агента + Service-маппинг в спеке |
| [12-domain-layer-and-ddd.md](12-domain-layer-and-ddd.md) | Терминология: analint = исполняемый тактический DDD; сага — домен, а не сервисы |
| [13-field-level-dsl.md](13-field-level-dsl.md) | Реформа полей: inline Lifecycle, Field-констрейнты и усиление типизации |
| [14-positioning-declarativity-and-audit.md](14-positioning-declarativity-and-audit.md) | Аудит после v1.0: Python как host language, декларативность, выразительность, Quint/P, роль DDD, soundness и новый roadmap |
| [15-quint-coin-comparison.md](15-quint-coin-comparison.md) | P6: перевод флагманского туториала Quint (coin.qnt) — паритет по объёму, стена множественности подтверждена делом |
| [16-nondeterministic-initial-states.md](16-nondeterministic-initial-states.md) | Перевод Quint Mafia: переходный недетерминизм уже есть, но explorer не квантифицируется по множеству допустимых начальных состояний |
| [17-engine-audit-and-realignment.md](17-engine-audit-and-realignment.md) | Эмпирический аудит движка и первый разворот от IR/bridge/Rust к engine completeness |
| [18-critical-audit-of-v1.3-direction.md](18-critical-audit-of-v1.3-direction.md) | Errata к 17: пропущенные false-green, canonical Init, `Action.by`, executable traces и исправленный порядок |
| [19-visualization-backends-and-positioning.md](19-visualization-backends-and-positioning.md) | Визуализация как diagnostics, границы IR/backends, Numba и честная ниша относительно Quint/FizzBee |
| [20-benchmark-strategy-before-transition-kernel.md](20-benchmark-strategy-before-transition-kernel.md) | Четыре разных benchmark-слоя: semantic conformance, graph characterization, synthetic scaling и внешний GitHub policy case |
| [21-playable-spec-experiment.md](21-playable-spec-experiment.md) | Executable traces and the limits of treating a specification as an interactive system |
| [22-event-dispatch.md](22-event-dispatch.md) | Evidence-based decision to keep `on` documentary and defer operational event-pool semantics |
| [23-evidence-github-branch-protection.md](23-evidence-github-branch-protection.md) | First external evidence model: GitHub branch protection, fidelity matrix, and measured requirement changes |
| [24-second-external-model-selection.md](24-second-external-model-selection.md) | Selection of OAuth Authorization Code with PKCE as the second external composition and identity model |
| [25-evidence-gate-synthesis.md](25-evidence-gate-synthesis.md) | Evidence-gate verdict: freeze semantic expansion while continuing the self-contained engine, diagnostics and measured scaling |
| [26-p4-self-contained-model-workbench-plan.md](26-p4-self-contained-model-workbench-plan.md) | Executable P4 plan: DSL/type audit, example intent contracts, exploration artifact, diagnostics, scaling and project-sized dogfooding |
| [27-dsl-type-boundary-audit.md](27-dsl-type-boundary-audit.md) | Audit of the embedded DSL's class/instance typing boundary and public export inventory |
| [28-p4.5-k8s-replicaset-dogfood.md](28-p4.5-k8s-replicaset-dogfood.md) | Kubernetes ReplicaSet + ResourceQuota dogfood: advanced authoring, diagnostics and measured friction |
| [29-ecosystem-and-first-public-release.md](29-ecosystem-and-first-public-release.md) | Packaging, compatibility and release-engineering decisions for the first public release |
| [30-dsl-contract-stabilization-review.md](30-dsl-contract-stabilization-review.md) | Pre-documentation API review: stable semantic kernel, bounded surface cleanup, rejected redesigns and freeze matrix |
| [31-goal-and-expressiveness-closure-audit.md](31-goal-and-expressiveness-closure-audit.md) | Strict goal/capability audit: finite-state semantic closure, evidence matrix, adversarial requirements and non-goals |
| [32-benchmarks-backends-and-terminal-ui.md](32-benchmarks-backends-and-terminal-ui.md) | Longitudinal performance benchmarks, trigger-based backend strategy, and a human-only read-only TUI gate |

Статус и приоритеты живут только в **[../ROADMAP.md](../ROADMAP.md)**.
Research-файлы — датированная аргументация и история решений.

**Апдейт после 08:** агентский сценарий признан главным, а не побочным —
ниша «проверяемая доменная спека для агентов» пуста при подтверждённом
спросе (Spec Kit/Kiro/Tessl — спеки без верификации; FM+LLM — верификация
без эргономики), а агенты инвертируют экономику поддержки спеки, убившую
идею у людей. Приоритеты пересобраны в 08 §7.

**Апдейт после 14:** к июню 2026 ниша уже не пуста: Quint и P развивают
LLM/MCP, model-based testing и runtime conformance. Уточнённое преимущество
analint — маленький domain-shaped embedded DSL и Python как готовая среда
авторинга, а не язык реализации описываемой системы. DDD признан полезным
профилем, но не фундаментом универсального ядра. Перед новой
выразительностью приоритет отдан soundness и устранению false-green.

**Апдейт после 16:** перевод Quint Mafia отделил два вида недетерминизма.
Explorer уже ветвится по enabled actions и bindings `Param`, но стартует
ровно из одного snapshot. Для проверки свойств при всех допустимых
конфигурациях нужен finite initial-state set и multi-source exploration;
это отдельная задача от Choice эффектов и bounded multiplicity.

**Апдейт после 17/18:** путь выразительности P4 закрыт, но engine audit нашёл
семантический долг: explorer игнорирует `Action.post`, общий результат считает
`INCONCLUSIVE` зелёным, у `Spec` нет canonical initial relation, а
`by/on/requires/Flow` выглядят семантическими сильнее, чем являются. Следующий
этап — не новые примитивы, а единый transition kernel, canonical Init,
executable traces и реальные внешние модели.

## Текущий синтез

- Ядро `state + invariant + transition + property` остаётся удачным.
- Reachability, multiplicity, quantifiers, initial sets и Create/Delete уже
  реализованы; старые документы до 17 описывают исторические ограничения.
- Концептуальный словарь мал, но public authoring surface уже содержит 48 имён.
  Новые слова требуют доказанной semantic density.
- `Scenario` is a concrete one-step example, `Flow` is an executable multi-step
  trace, and a query performs bounded exploration. Before stabilizing its result
  artifact, P4 audits the authored DSL type boundary and makes every example's
  expected outcome executable; the next result level is then a stable
  exploration artifact with state diffs and completeness.
- JSON-IR, implementation bridge, semantic diff и Rust отложены; внутреннюю
  единую transition semantics откладывать нельзя.
- Two external models closed the evidence gate: new primitives remain frozen
  until pain recurs. Active work is the self-contained bounded engine,
  diagnostics, scaling and additional project-sized models.
- The pre-documentation contract review (research/30) confirms the semantic
  kernel and rejects a new textual/logic/natural-language DSL. Documentation is
  gated on a bounded cleanup: remove semantic-looking metadata, simplify
  checkpoints/lifecycle/boolean predicates, fix repeated scope identity and
  initial-presence friction, and version all machine-facing JSON contracts.
- The strict goal audit (research/31) finds semantic closure for the intended
  bounded safety/reachability scope: no new verification primitive is required.
  It also identifies a claims bug to fix before publication: `NoDeadEnd` proves
  recoverability, not inevitable settlement/liveness.
- The benchmark/backend/TUI follow-up (research/32) distinguishes realistic
  evidence models from performance benchmarks, adds ASV-style history over the
  existing workloads, defers another verifier until a measured trigger, and
  treats a TUI as an optional human navigator after API/docs stabilization.

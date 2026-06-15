# analint — Концепция

## Проблема

Поведение систем сегодня описывают в Word, Confluence, Miro — текст и схемы
нельзя проверить на противоречия, нельзя сделать diff, нельзя передать агенту.
Код — другая крайность: слишком детально, бизнес его не читает, а целиком его
не охватывает даже агент.

analint занимает промежуточное место: **компактная исполняемая модель
поведения системы, которую человек и агент могут читать, запрашивать,
менять и верифицировать — до того, как трогать реализацию.**

Важно: Python здесь — язык *авторинга* спецификации, а не язык реализации
описываемой системы. Модель может описывать сервис на любом языке, игру,
workflow или процедуру без программной реализации вовсе.

## Фундаментальная модель

```
состояние + факты + переходы + наблюдения + запросы
```

Публичный словарь (см. README для деталей):

| Примитив | Роль |
|---|---|
| `Entity` + `Field` + `Lifecycle` | типизированное состояние: поля, домены значений, допустимая динамика |
| `Invariant` | факт обо всех состояниях мира (межполевые/межсущностные отношения) |
| `Action` (pre / effect / post) | переход: охрана + одновременные факты о следующем состоянии |
| `Event` (emits / on) | типизированное наблюдение/связь; операционная event semantics пока не определена |
| `Scenario` (given / then) | конкретный пример: позитивный или заблокированный путь |
| `Reachable` / `Unreachable` / `AlwaysHolds` / `NoDeadEnd` / `DeadActions` | запросы к движку по всему пространству состояний |

Семантика декларативна без исключений: эффекты — не команды, а одновременные
факты о следующем состоянии (правые части читаются из пред-состояния, порядок
списка не значим); предикаты — анализируемые AST-значения, не callbacks.

## Два уровня проверки

1. **Сценарии** — проверяют состояния, о которых автор подумал
   (инварианты → pre → эффекты → post → then).
2. **Запросы движка** — bounded reachability: исчерпывающий BFS по всем
   достижимым состояниям находит то, о чём автор *не* подумал: софтлоки,
   недостижимые цели, нарушения инвариантов в глубине процесса. Каждый
   вердикт несёт трассу-контрпример, читающуюся как мини-сюжет.

Целевой принцип доверия: верификатор продаёт доверие к PASS. Текущий аудит
нашёл нарушения этого принципа (`Action.post` в explorer и общий PASS при
`INCONCLUSIVE`); они являются P0 текущей фазы (research/18).

## Для кого

- **AI-агенты** — главный сценарий: спека как сжатая, запрашиваемая модель
  мира (`analint show` / `affects` / MCP), what-if проверка гипотез до правки
  кода, внешний верификатор вместо самопроверки (research/08).
- **Команды с долгоживущими системами** — доменное ядро как проверяемый
  источник истины; человек ревьюит дифф модели, а не сорок файлов кода.
- **Гейм- и нарративный дизайн** — правила и сюжет как верифицируемая
  модель: достижимость концовок, отсутствие тупиков (examples/cloak,
  examples/trollbridge).

## Позиционирование

Не «универсальный формальный язык» (это Quint/TLA+/P/FizzBee — мощнее или
зрелее на своих задачах) и
не «DSL для Python-бэкендов» (модель не привязана к реализации). Честная
формула:

> Domain-shaped язык поведения поверх готовой Python-экосистемы:
> маленькое концептуальное ядро, высокая плотность предметного смысла,
> agent-friendly интроспекция и контрпримеры.

This positioning remains a hypothesis rather than proven uniqueness. The overlap
with Quint and especially FizzBee is substantial: Python-like authoring, model
checking, traces, visualization, MBT and agent tooling already exist. analint's
possible niche is a schema-first **domain contract verifier** optimized for
composition, impact analysis, what-if work and safe maintenance of a long-lived
model by coding agents, rather than maximum formal expressiveness. Two external
evidence models supported the usefulness of bounded reachability without
demanding new verification primitives. The project remains self-contained:
Quint is an independent comparison, not the target backend architecture
(research/24-25).

DDD — полезный профиль и общий язык с бэкенд-аудиторией (Entity/Invariant/
Event совпадают со словарём Эванса почти дословно), но не фундамент ядра.
Top-level API уже широк (48 экспортов), поэтому минимализм оценивается не
числом имён, а semantic density и разделением core/advanced surface.

## Дальше

Current state, phases and priorities live in `ROADMAP.md`; decision history lives
in `research/00-overview.md`. The next milestone is a self-contained model
workbench. It starts by making the authored DSL type contract and example intent
explicit, then adds a stable exploration artifact, state-diff diagnostics,
measured scaling and continued validation on larger real models (research/25-26).

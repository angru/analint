# Кейс-стади: Cloak of Darkness + «Тролий мост»

Проверяем выразительность DSL на настоящих игровых механиках. Без кода —
моделирование на бумаге, чтобы найти дыры и проверить читаемость.

## Почему эти игры

**Cloak of Darkness** (Roger Firth, 1999) — каноничный бенчмарк IF-систем:
крошечная игра, специально придуманная, чтобы её реализовывали на Inform,
TADS, Hugo и т.д. и сравнивали системы между собой. Реализовать её на
analint — буквально встать в этот ряд. В ней есть: перемещение по локациям,
инвентарь (плащ), скрытое состояние мира (затоптанность послания),
действия с побочными эффектами и две концовки.

**«Тролий мост»** — придуманная мини-RPG-виньетка, добавленная потому, что
в Cloak почти нет числовых механик, а пользовательский запрос — именно
«жизни уменьшаются, инвентарь меняется». Заодно в неё специально заложен
softlock — проверить, какие проверки могли бы его поймать.

## Часть 1. Cloak of Darkness

### Правила игры (оригинальная спецификация)

Три комнаты: Фойе (старт), Гардероб (на западе), Бар (на юге). Игрок одет
в бархатный плащ. Пока плащ при нём — в Баре темно, и любое действие в
темноте затаптывает послание, выложенное в опилках на полу. Плащ можно
повесить на крючок в Гардеробе — тогда в Баре светло и послание можно
прочитать. Если оно затоптано не сильно (≤1 раз) — победа, иначе — поражение.

### Модель в предлагаемом DSL (из 05-universal-dsl.md)

```python
class Room(Enum):
    FOYER = "foyer"; CLOAKROOM = "cloakroom"; BAR = "bar"

class Result(Enum):
    PLAYING = "playing"; WON = "won"; LOST = "lost"

class Player(Entity):
    location: Room = Room.FOYER
    has_cloak: bool = True          # плащ надет с самого начала

class Hook(Entity):
    holds_cloak: bool = False

class Message(Entity):
    disturbances: int = 0           # сколько раз затоптали

class Game(Entity):
    result: Result = Result.PLAYING


# ── перемещение ──
go_west  = Action(pre=[Player.location == Room.FOYER],
                  effect=[Set(Player.location, Room.CLOAKROOM)])
go_east  = Action(pre=[Player.location == Room.CLOAKROOM],
                  effect=[Set(Player.location, Room.FOYER)])
go_south = Action(pre=[Player.location == Room.FOYER],
                  effect=[Set(Player.location, Room.BAR)])
go_north = Action(pre=[Player.location == Room.BAR],
                  effect=[Set(Player.location, Room.FOYER)])

# ── плащ ──
hang_cloak = Action(
    pre=[Player.location == Room.CLOAKROOM, Player.has_cloak == True],
    effect=[Set(Player.has_cloak, False), Set(Hook.holds_cloak, True)],
)

# ── темнота: в баре с плащом любое действие топчет послание ──
grope_in_dark = Action(
    pre=[Player.location == Room.BAR, Player.has_cloak == True],
    effect=[Add(Message.disturbances, 1)],
)

# ── две концовки ──
read_message_win = Action(
    pre=[Player.location == Room.BAR, Player.has_cloak == False,
         Message.disturbances <= 1, Game.result == Result.PLAYING],
    effect=[Set(Game.result, Result.WON)],
)
read_message_lose = Action(
    pre=[Player.location == Room.BAR, Player.has_cloak == False,
         Message.disturbances >= 2, Game.result == Result.PLAYING],
    effect=[Set(Game.result, Result.LOST)],
)

game_over = Lifecycle(Game.result, initial=Result.PLAYING,
                      transitions=[Transition(Result.PLAYING, [Result.WON, Result.LOST])])

# ── сценарии-примеры (работают уже на сегодняшнем движке) ──
sc_clean_win = Scenario(
    given=[Player(location=Room.BAR, has_cloak=False), Hook(holds_cloak=True),
           Message(disturbances=0), Game()],
    action=read_message_win,
    then=[Assert(Game.result == Result.WON)],
)

# ── запросы к будущему движку ──
Reachable(Game.result == Result.WON)     # победа вообще возможна
Reachable(Game.result == Result.LOST)    # и поражение тоже (иначе зачем оно)
NoDeadEnd(goal=Game.result != Result.PLAYING)  # игра всегда может закончиться
```

**Вся игра — ~60 строк, читается вслух без подготовки.** Для сравнения:
реализация на Inform 7 — ~40 строк, на TADS — ~100. Мы в правильном классе
размеров, при этом получаем верификацию, которой нет ни у одной IF-системы.

### Та же `hang_cloak` на текущем DSL — для контраста

```python
rule_in_cloakroom = BusinessRule(
    id="in-cloakroom", name="Player must be in the cloakroom",
    rule_type=RuleType.PRECONDITION,
    expression=Player.location == Room.CLOAKROOM,
)
rule_wearing = BusinessRule(
    id="wearing-cloak", name="Player must be wearing the cloak",
    rule_type=RuleType.PRECONDITION,
    expression=Player.has_cloak == True,
)
uc_hang_cloak = UseCase(
    id="hang-cloak", name="Hang the cloak on the hook",
    entities=[Player, Hook],
    rules=[rule_in_cloakroom, rule_wearing],
    effects=[Set(Player.has_cloak, False), Set(Hook.holds_cloak, True)],
)
```

17 строк против 4. На всю игру: ~210 строк против ~60. Содержание идентично —
вся разница в церемонии. Это главный аргумент за реформу из 05.

### Найденные дыры (ради этого всё и затевалось)

1. **Условные исходы.** «Прочитать послание» — одно действие игрока с двумя
   исходами в зависимости от состояния. Пришлось разрезать на
   `read_message_win` / `read_message_lose` с взаимоисключающими pre.
   Работает, но не масштабируется (3 исхода × 2 условия = 6 действий).
   Нужен либо `Choice/outcomes`, либо условные эффекты.
2. **Derived-состояние.** «В баре темно» — это не хранимое поле, а функция:
   `dark ⟺ has_cloak`. Пришлось инлайнить `Player.has_cloak == True` в pre
   каждого «тёмного» действия. При 2 действиях терпимо; при 20 — источник
   рассинхрона. Кандидат: `Computed(...)`.
3. **Нет `Implies`.** Инвариант «если плащ на крючке, то его нет у игрока»
   выражается только как `Or(Not(Hook.holds_cloak == True), Player.has_cloak == False)` —
   нечитаемо. `Implies(a, b)` — обязательное дополнение к комбинаторам.
4. **Параметризация перемещения.** 4 действия `go_*` вместо одного
   `go(from, to)` — налог отсутствия параметров. На 3 комнатах — мелочь,
   на 30 — катастрофа. Подтверждает приоритет параметризации из 04/05,
   но *для прототипа не блокер*.
5. **Терминальное состояние.** «Игра окончена, действия запрещены» пришлось
   вшивать как `Game.result == Result.PLAYING` в pre концовок (а по-хорошему —
   во все действия). Частый паттерн (смерть персонажа, закрытый заказ) —
   заслуживает сахара, например `Lifecycle(..., terminal=[WON, LOST])`,
   автоматически блокирующего действия над «мёртвой» сущностью.

**Чего НЕ потребовалось:** множественные экземпляры (все сущности —
естественные синглтоны!), кванторы, агрегаты. Гипотеза «на синглтонах можно
жить долго» кейсом подтверждается.

## Часть 2. «Тролий мост» — числовые механики и softlock

### Правила

У героя 10 HP и 6 золотых. В лавке: меч за 5, зелье за 3 (можно пить, +4 HP).
Мост стережёт тролль: бой с мечом стоит 3 HP, без меча — 12 HP (смерть).
Цель — перейти мост (тролль должен быть мёртв, герой — жив).

```python
class Hero(Entity):
    hp: int = 10        # хочется: int[0..14] — границы для движка
    gold: int = 6
    has_sword: bool = False
    potions: int = 0

class Troll(Entity):
    alive: bool = True

class Quest(Entity):
    bridge_crossed: bool = False

hero_alive = Hero.hp > 0                     # переиспользуемый предикат

buy_sword    = Action(pre=[hero_alive, Hero.gold >= 5, Hero.has_sword == False],
                      effect=[Subtract(Hero.gold, 5), Set(Hero.has_sword, True)])
buy_potion   = Action(pre=[hero_alive, Hero.gold >= 3],
                      effect=[Subtract(Hero.gold, 3), Add(Hero.potions, 1)])
drink_potion = Action(pre=[hero_alive, Hero.potions >= 1],
                      effect=[Subtract(Hero.potions, 1), Add(Hero.hp, 4)])

fight_armed     = Action(pre=[hero_alive, Troll.alive == True, Hero.has_sword == True],
                         effect=[Set(Troll.alive, False), Subtract(Hero.hp, 3)])
fight_barehand  = Action(pre=[hero_alive, Troll.alive == True, Hero.has_sword == False],
                         effect=[Set(Troll.alive, False), Subtract(Hero.hp, 12)])

cross_bridge = Action(pre=[hero_alive, Troll.alive == False],
                      effect=[Set(Quest.bridge_crossed, True)])

# запросы к движку
AlwaysHolds(Hero.hp >= 0)                    # ← НАРУШАЕТСЯ, см. ниже
NoDeadEnd(goal=Quest.bridge_crossed == True) # ← НАРУШАЕТСЯ, см. ниже
```

### Что нашёл бы движок (и не найдёт ни один ручной сценарий)

**Нарушение `AlwaysHolds(Hero.hp >= 0)`** — трасса-контрпример:
`fight_barehand` → hp = 10 − 12 = **−2**. Эффекты не клампятся, инвариант
пробит. Автор либо добавляет кламп/правило смерти, либо понимает, что
забыл смоделировать гибель героя. Текущий снапшот-движок это поймает
*только если автор сам догадается написать такой сценарий* — т.е. поймает
только уже заподозренный баг.

**Нарушение `NoDeadEnd`** — трасса: `buy_potion, buy_potion` → золото 0,
меча нет и не будет, бой без меча убивает → `bridge_crossed` недостижим.
**Классический softlock, заложенный в экономику** (6 золотых: либо меч,
либо два зелья). Это ровно тот класс багов, из-за которых игры патчат после
релиза, и который по определению не ловится ручными сценариями — автор
не пишет тест на ситуацию, о которой не подумал.

Обе находки — короткие трассы, читающиеся как мини-сюжет («герой купил два
зелья и обрёк себя»). Это подтверждает тезис 05: контрпример-трасса —
лучший формат сообщения об ошибке для этого домена.

### Числовая специфика

Поля `hp/gold/potions` делают пространство состояний условно-бесконечным.
Но фактические диапазоны крошечные: hp ∈ [−2..14], gold ∈ [0..6],
potions ∈ [0..2] — при заявленных границах полный перебор тривиален
(тысячи состояний). Вывод: **границы на числовых полях**
(`hp: int = Field(10, ge=0, le=14)` или аннотация `int[0..14]`) — необходимое
и достаточное условие для движка. Без границ — graceful degradation до
сегодняшнего снапшот-режима.

## Итоги кейс-стади

| Вопрос | Ответ |
|---|---|
| Выразимы ли реальные игровые механики? | Да, обе игры целиком, без потери смысла |
| Хватает ли синглтонов? | Да — для игр этого масштаба полностью |
| Читаемо ли «обычным человеком»? | Предлагаемый синтаксис — да (тест чтения вслух); текущий — тонет в церемонии (~3.5× строк) |
| Что добавить в язык срочно | `Implies`; условные исходы (`Choice`); терминальные состояния в `Lifecycle` |
| Что добавить позже | derived-поля, параметризация действий, границы числовых полей |
| Что даёт движок такого, что нельзя руками | softlock и пробитие инварианта — баги, на которые автор *не догадается* написать сценарий |

Следующий шаг, когда дойдём до кода: реализовать Cloak of Darkness как
`examples/cloak/` на текущем DSL (он способен, просто многословен) — это
живой тест миграции на новый словарь и будущий бенчмарк движка.
Кандидат покрупнее на потом: The Intercept (открытый ink-пример Inkle) —
проверить импорт реального нарративного графа.

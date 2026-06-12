# Pilot agronomists & field responsibilities

Pilot expanded 2026-06-12: three junior agronomists added, each responsible for
one Соя / Озимая пшеница / Подсолнечник field. **Field responsibility is
organizational** — the bot's picker shows all pilot fields to everyone (founder's
choice); this table is the record of who covers what. Each agronomist still
needs a bot account (whitelisted by Telegram ID via `/adduser`).

Field notation from the farm is `номер/площадь-га` (e.g. `119/107` = field №119,
107 ha). In the DB the whole-farm import named them `Поле <номер> · <группа>`.

| Agronomist | Crop | Farm notation | DB field | id |
|---|---|---|---|---|
| **Олег Костенников** | Соя | 119/107 | Поле 119 · Хлевище | 142 |
| | Озимая пшеница | 49/95 | Поле 49 · Красное | 214 |
| | Подсолнечник | 170/53 | Поле 170 · Хлевище | 108 |
| **Валерий Швец-Ковган** | Соя | 268/53 *(DB area 55 ha)* | Поле 268 · Хлевище | 239 |
| | Озимая пшеница | 10/61 | Поле 10 · Красное | 27 |
| | Подсолнечник | 144/134 | Поле 144 · Хлевище | 110 |
| **Олег Сорока** | Соя | 39/113 | Поле 39 · Красное | 198 |
| | Озимая пшеница | 32/232 | Поле 32 · Красное | 13 |
| | Подсолнечник | 217/81 | Поле 217 · Красное | 66 |

These 9 fields were flipped to `is_pilot = true` in migration 0020 (alongside the
original 3: Поле 76/108, 121/140, 171/99). The full farm's treatment history is
already loaded, so each field's `/field` card works.

## Onboarding the agronomists (needs their Telegram ID)
1. Each agronomist opens the bot and presses **Start**. Not yet whitelisted, the
   bot refuses them and **shows their Telegram ID** — they send it to the admin.
2. Admin runs, in the bot, for each:
   - `/adduser <tg_id> Олег Костенников`
   - `/adduser <tg_id> Валерий Швец-Ковган`
   - `/adduser <tg_id> Олег Сорока`
3. They press Start again — the bot lets them in. They upload to their fields
   from the picker (all pilot fields shown) or via «Другое поле (по номеру)».

# Bot → CropWise push — status (blocked on CropWise support)

*As of 2026-06-15.*

Goal: an agronomist reports an операция to the bot (voice/NL) → it's created in
CropWise automatically, no double entry. Reverse of the read sync.

## What works (proven against live CropWise)
- `catalog/cropwise_push.py` parses a note (`bot/parse_op.py`), maps it to
  CropWise dictionaries, and **creates an agro_operation** — `POST /agro_operations`
  returns **201**. Field, work-type, product, rate, unit, date, idempotency_key all
  map correctly (e.g. поле 121 → CW field 158, Корсар → Chemical 51, unit 26 liter).
- Update (`PUT`) and delete (`DELETE → 204`) also work — **the token has full write
  access** (the probe returned 422 validation, not 403; create+delete succeeded).
- CLI: `python -m catalog.cropwise_push --note "…"` (dry preview) / `--post` (create)
  / `--delete <id>` (cleanup). Two-step create-then-complete is implemented.

## The blocker
Operations are created as **«Запланировано» (planned)**. Marking them **«Сделано»
(done)** fails with `422 strict_ami_done_status` — *«отсутствуют внесения»*.

The mobile app confirms why: completion is **not** a status you pick (the Статус
screen only offers Запланировано / В процессе / Отменено). «Сделано» is **derived**
— it happens only after you add a **внесение** (actual application record) on the
**Внесения** screen. That внесение is a **separate entity** from
`application_mix_items`, and the app does **not** pre-fill it from the planned mix
(you re-enter product/dose/area). So pre-fill-and-tap saves little — full
automation is the only worthwhile version, and it needs the внесение API.

Guessed endpoints `/ao_applications`, `/applications`,
`/agro_operation_applications` all 404. The внесение creation method is
undocumented → asked CropWise support (question sent 2026-06-15).

## Question sent to CropWise support
> API v3 — как создать «внесение» (фактическое применение) у агрооперации, чтобы
> она перешла в «Сделано»? Создание операций работает (POST → 201), но `status=done`
> даёт `422 strict_ami_done_status` («отсутствуют внесения»). В приложении внесение
> добавляется отдельно на экране «Внесения». Какой endpoint и поля? Можно ли создать
> операцию сразу с внесением в одном запросе? (`/ao_applications`, `/applications` → 404)

## Resume when CropWise answers
1. Add a `create_внесение` step to `cropwise_push.py` using their endpoint/fields,
   called after the operation is created, then mark done.
2. Re-test with `--post` on a pilot field; verify status «Сделано»; delete the test op.
3. Wire into the bot `/log` confirm step (founder chose **confirm-before-push** +
   **push op, flag unmatched product**). Add idempotency dedup so the weekly pull
   (`cropwise_ops_sync`) doesn't re-import our own pushes.

Feature decisions already made: confirm-before-send; unmatched product → still
create the op, flag the product for manual entry.

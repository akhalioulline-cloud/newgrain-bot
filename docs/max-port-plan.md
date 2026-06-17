# Max (МАКС) front-end — port plan

*As of 2026-06-17. Decision: Telegram is the PRIMARY front-end; Max is a secondary
MIRROR. Strategic driver: Max is RU-state-backed (no RKN throttling, unlike Telegram
which we relay via Cloudflare), and the agronomists + Max-reports already live there.*

## Architecture: one backend, two adapters
The bot is **one system with two doors**, not two bots:

- **Shared backend (platform-agnostic, reused by both):** `bot/db.py`, `catalog/*`
  (CropWise sync/push, report parser), `bot/agro_chat.py`, `bot/parse_op.py`,
  `bot/transcribe.py`, `bot/weed_suggest.py`, NDVI, storage. All write to the **same
  Postgres + CropWise** — so an op logged via Max is identical to one via Telegram.
- **Telegram adapter (`bot/`, aiogram) — PRIMARY:** the reference UX. Features are
  built and tested here first; it's the guaranteed-working one. If Max's API can't
  match a behavior, Telegram wins and Max approximates. Never regressed for Max's sake.
- **Max adapter (`bot_max/`, to build) — MIRROR:** Max Bot API + its Python SDK
  (`github.com/max-messenger/max-botapi-python`; aiogram-style `@dp.message_created()`).
  Calls the same backend functions; mirrors Telegram's flows; may lag.

## Gating requirement (founder)
Max permits publishing bots only via a **verified RU legal entity** under a license
agreement (the open @MasterBot self-serve was closed in 2025). Register **АО «НЗК»**
as a verified Max bot publisher → get a **bot token**. The Max build is BLOCKED on this:
can't develop/test against Max without the token + account.

## Plan (after the token exists)
1. Build `bot_max/` adapter; port a **pilot** — `/log` (operation logging) + the
   conversational Q&A — to validate parity.
2. **Parity to confirm in the pilot** (Max is a full messenger, so likely yes, but
   behaviors differ): inline buttons + callbacks (our field/category/species pickers,
   confirm cards), photo upload+download, voice messages (for SpeechKit transcription),
   location sharing, FSM-style conversation state.
3. If parity holds, port the rest (photo flow, CA review, report-paste, /field, etc.),
   mirroring Telegram.
4. Telegram stays primary + stable throughout. Lift shared logic OUT of `bot/handlers.py`
   into platform-agnostic modules **only as the Max adapter needs it**, incrementally,
   without destabilizing the live Telegram bot. (Much logic — slot-filling, report
   parsing, field resolution — currently lives in handlers.py and would be extracted.)

## Notes
- Fully in-RU stack (Max + Yandex Object Storage + CropWise + YandexGPT) → clean for
  152-ФЗ, and **no Cloudflare relay needed** on the Max side (Max isn't RKN-blocked).
- Same `field_treatments` / submissions / users tables; a user could use either door.
  (Open question for later: do we key users by a single identity across both messengers,
  or treat Max user-ids separately? Decide when porting onboarding/auth.)

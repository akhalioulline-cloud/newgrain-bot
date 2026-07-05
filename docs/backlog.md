# Flagleaf / EAR — Backlog

Deferred work + ideas, parked here on purpose so we don't lose them and don't build them
prematurely. Ask "show me the backlog" anytime. Newest asks near the top of each section.

_Last updated: 2026-07-05 (Telegram-gap review with the founder; order below is the agreed one)._

## Messenger features — agreed plan (5 Jul 2026 review vs Telegram)

**Done in the 5 Jul batch:**
- ~~Camera & photo/video into the feed~~ — composer camera button → камера/галерея → upload →
  Flagleaf recognizes (expo-image-picker; iOS permission strings staged for the EAS build).
- ~~Bot-chat («Личное» w/ Flagleaf) server-side~~ — migration 0040 `bot_chat_messages`;
  survives restarts, syncs across devices (`/api/chat/history`).
- ~~Push backend~~ — `push_tokens` per DEVICE (multi-device by design), `/api/push/register`,
  Expo push sends on: new person-DM, feed comment on your post, chief's verdict. **Delivery
  waits on the EAS build** (Expo Go ≥SDK 53 can't receive remote push) — client registration
  is the next step there.
- ~~Full-screen photo viewer~~ — tap feed photo → zoomable viewer (domain-critical for diagnosis).
- ~~Read receipts ✓/✓✓~~ in person DMs (gold ✓✓ when read).
- ~~Date separators~~ («сегодня»/«вчера»/дата) in DM threads; feed poll (12 s) + thread poll (6 s).

**Next up (agreed order):**
1. **EAS build** — unlocks push delivery + frees the app from the founder's Mac (TestFlight /
   direct install). Client push registration lands with it.
2. **Voice messages with auto-transcription** — record in composer, voice + Whisper text both
   shown (pipeline already in prod for the Telegram bot). Field-first differentiator.
3. **Chat polish batch:** edit/delete own messages · typing indicator in person DMs («печатает…»)
   · unread badge for the feed row (needs local last-seen storage).
4. **Offline capture queue** (M1 leftover) — dead-zone photo → queued → auto-send. After camera
   + push prove the loop.

**Parked (Tier 3 — revisit when usage justifies):**
- Search across chats/feed (needs months of history to matter).
- Albums (multi-photo scouting series in one post).
- @mentions in the feed (team of 8 reads everything).
- Polls («обрабатываем 121-е завтра?») — fun, not core.
- WebSocket live updates — polling (6–20 s) is fine at pilot scale; push notifications cover
  the "know immediately" need once EAS lands.
- Web-app parity for person DMs; media in person DMs.

## Product / EAR (the chat)
- ~~Private human-to-human chats~~ — **DONE 5 Jul 2026** (migration 0039 `dm_messages`,
  `/api/dm/*`, native chat-list rows + thread view with unread badges).
- Chief-review reactions (👍/👎) in the **native** feed (web has them; native shows the verdict
  badge but no react buttons yet).
- «Ваш вклад» / team-goal + «мои загрузки» in native (web-only for now).

## Native app (Expo) — Milestone roadmap
- **M1 remaining:** ~~camera/media capture~~ ✅ · push **delivery** (backend ✅, needs EAS build) ·
  offline capture queue.
- **M2:** on-device offline recognition (our fine-tuned model via Core ML/TFLite; instant guess
  offline → auto-upgrade to qwen online).
- **M3:** AR (live camera overlay) — the wow, last.
- EAS build / store presence (RuStore Android; iOS TestFlight/sideload) — promoted to "next up"
  above (push depends on it).

## Backend / architecture
- **Finish Flagleaf/Ear separation:** migrate the still-coupled surfaces to `flagleaf.respond()`
  — Telegram `bot/handlers.py`, `/api/diagnose`, `/api/diagnose-video`, `/api/chat`+`/api/chat/stream`
  (feed already done). Removes duplicated orchestration.
- ~~Native-push token backend path~~ — **DONE 5 Jul 2026** (migration 0040 `push_tokens`).
- `/api/chat/stream` doesn't persist bot-chat turns (only `/api/chat` does) — align when the
  native app moves to streaming replies.

## AI / learning
- **Train from the discussion**: use feed **comments** (peers correcting each other) as a training
  signal — captured today, not yet fed to the model. Chief 👍/👎 already drives the labeling gate.
- Condition-/threshold-triggered product surfacing (idea borrowed from AgriChat.AI): surface
  Госкаталог products exactly when a recognized weed/pest + ЭПВ threshold calls for it — a grounded
  future monetization.
- EPPO grounding (RU→Latin bridge; bulk download portal was buggy — deferred).

## Research / ops
- Deeper teardown of the closest competitors: **Xsupra/Alora** (agri-chat.de — same field-grounding
  thesis) and **«Андрей Тимофеевич»** (RU, photo diagnosis). See `docs/competitors.md`.
- Announce shipped features via `_ANNOUNCEMENTS` — **on hold** until the founder does an on-device
  pass and gives the go.
- Scout reminder cron — removed by design (intrinsic motivation); not a backlog item, noted so we
  don't re-add it by reflex.

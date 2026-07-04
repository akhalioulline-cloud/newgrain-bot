# Flagleaf / EAR — Backlog

Deferred work + ideas, parked here on purpose so we don't lose them and don't build them
prematurely. Ask "show me the backlog" anytime. Newest asks near the top of each section.

_Last updated: 2026-07-04._

## Product / EAR (the chat)
- **Private human-to-human chats** — agronomist ↔ agronomist direct messages (not just you↔bot).
  Bigger build: new backend for person-to-person threads (conversations, membership, unread),
  new UI. «Личное» today is you↔bot only. _(Parked 4 Jul 2026 at founder's request.)_
- Chief-review reactions (👍/👎) in the **native** feed (web has them; native shows the verdict
  badge but no react buttons yet).
- «Ваш вклад» / team-goal + «мои загрузки» in native (web-only for now).

## Native app (Expo) — Milestone roadmap
- **M1 remaining:** camera/media capture (photo+video → recognition into the feed); **push
  notifications** (biggest engagement lever — needs a native-token path on the backend); offline
  capture queue (dead-zone → auto-send). _(«Личное» DM done 4 Jul.)_
- **M2:** on-device offline recognition (our fine-tuned model via Core ML/TFLite; instant guess
  offline → auto-upgrade to qwen online).
- **M3:** AR (live camera overlay) — the wow, last.
- Eventually: dev build / EAS + store presence (RuStore Android; iOS TestFlight/sideload) when we
  outgrow Expo Go or ship publicly.

## Backend / architecture
- **Finish Flagleaf/Ear separation:** migrate the still-coupled surfaces to `flagleaf.respond()`
  — Telegram `bot/handlers.py`, `/api/diagnose`, `/api/diagnose-video`, `/api/chat`+`/api/chat/stream`
  (feed already done). Removes duplicated orchestration.
- Native-push token backend path (parallel to the web-push VAPID path) — pairs with M1 push.

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

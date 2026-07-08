# Flagleaf / EAR — Backlog

Deferred work + ideas, parked here on purpose so we don't lose them and don't build them
prematurely. Ask "show me the backlog" anytime. Newest asks near the top of each section.

_Last updated: 2026-07-05 (flat wall shipped; deploy-order lesson noted)._

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

## Founder asks 7 Jul 2026 (suggested order: 3 → 4 → 5 → 1a → 2 → 1b)
1. **Encryption** — (a) at-rest (YC disk/backup encryption): EASY, do soon. (b) E2E: HARD and
   incompatible with Flagleaf reading the wall (bot/learning/verdicts); only feasible for
   person-DMs (bot-free) — parked unless demanded. In-transit already HTTPS.
2. **English version** — UI i18n (expo-localization + RU/EN dict): EASY (~2 days). English
   AI answers = dual-market grounding project (Госкаталог/ЭПВ are RU) — schedule with the
   relocation/dual-market push.
3. ~~Add users without Telegram~~ — **DONE 7 Jul** (POST /api/invite, person-add button in home
   header for admin/chief, invite email; negative synthetic tg_user_id = email-only login).
4. ~~Leaf-contour chat wallpaper~~ — **DONE 7 Jul** (seamless tileable leaf outlines, light+dark,
   behind all three chats).
5. **User photos (avatars)** — upload → S3 → shown everywhere (initials fallback). EASY-MODERATE
   (~1 day incl. backend).

## Product / EAR (the chat)
- ~~Flat team wall~~ — **DONE 5 Jul 2026.** Team chat is now ONE flat message stream (migration
  0041 `wall_messages`/`wall_reactions`, replaced posts+threads; old feed migrated in). @flagleaf
  summons the bot (photos still auto-reply); reply/quote via long-press; @mention teammates
  (autocomplete + push + highlight); chief 👍/👎 inline. ~~Web/native divergence~~ — **FIXED 8 Jul**: web
  feed.html rewritten onto /api/wall (flat wall, reply-quote, @flagleaf, chief verdicts);
  assistant.html seeds server-side bot-chat history. Old `/api/feed*` endpoints now unused —
  retire in a later cleanup.
- ~~Private human-to-human chats~~ — **DONE 5 Jul 2026** (migration 0039 `dm_messages`,
  `/api/dm/*`, native chat-list rows + thread view with unread badges).
- ~~Chief-review reactions in native~~ — **DONE** (👍/👎 inline on wall photo messages → labeling gate).
- Wall niceties: tap a reply-quote to scroll to the original; swipe-to-reply (Telegram gesture,
  currently long-press → Ответить); edit/delete own messages; feed-row unread badge.
- «Ваш вклад» / team-goal + «мои загрузки» in native (web-only for now).

## Native app (Expo) — Milestone roadmap
- **M1 remaining:** ~~camera/media capture~~ ✅ · push **delivery** (backend ✅, needs EAS build) ·
  offline capture queue.
- **M2:** on-device offline recognition (our fine-tuned model via Core ML/TFLite; instant guess
  offline → auto-upgrade to qwen online).
- **M3:** AR (live camera overlay) — the wow, last.
- ~~EAS build~~ ✅ (7 Jul: builds #1–5, push, version stamp).
- **OTA updates are SELF-HOSTED as of 8 Jul** (`scripts/publish_ota.py` → ai.flagleaf.ru;
  `/api/ota/manifest` + nginx-static assets) — Expo's CDN silently 403'd all our update assets
  ('Unauthorized asset request', no dashboard/email explanation; suspected new-account
  anti-abuse). EAS still does builds + push. Optional: forum ticket to Expo w/ evidence.
- **Store presence** (researched 8 Jul 2026; OTA stays allowed & unchanged in ALL stores — JS/asset
  OTA is policy-compliant, only native builds go through review):
  - **RuStore — first, candidate for NOW:** free dev account (VK ID, console.rustore.ru), accepts
    our EAS APK, moderation ~1–3 days, no tester quotas. To solve: (a) login-walled app needs
    review access → demo account on the DEMO farm (migration 0003) + static login code accepted
    only for the review email; (b) privacy policy page at ai.flagleaf.ru/privacy (~half a day);
    (c) listing assets (icon ✓, screenshots from device, RU description). Caveat: FCM push needs
    Google services on the phone — no-GMS devices (Huawei) later need the RuStore push SDK (native).
  - **Google Play — later (go-public/dual-market):** $25 once, non-RU card; PERSONAL accounts must
    run a closed test with 12+ testers for 14 days before production (org accounts exempt); AAB via
    `eas submit`; privacy-policy + data-safety paperwork. Decide account country/identity together
    with Apple.
  - **App Store — after Apple Developer enrollment** (TestFlight for the team first; storefront at
    go-public).

## Backend / architecture
- **Finish Flagleaf/Ear separation:** migrate the still-coupled surfaces to `flagleaf.respond()`
  — Telegram `bot/handlers.py`, `/api/diagnose`, `/api/diagnose-video`, `/api/chat`+`/api/chat/stream`
  (feed already done). Removes duplicated orchestration.
- ~~Native-push token backend path~~ — **DONE 5 Jul 2026** (migration 0040 `push_tokens`).
- `/api/chat/stream` doesn't persist bot-chat turns (only `/api/chat` does) — align when the
  native app moves to streaming replies.

## AI / learning
- **Proactive Flagleaf — SHADOW MODE running (5 Jul):** unsummoned messages evaluated + logged
  (would-be line), nothing posted. Read `flagleaf_shadow` / `GET /api/shadow` together; decide if
  it graduates to 'live' (rate-limited, maybe private-DM). See [[newgrain-flagleaf-proactive]].
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

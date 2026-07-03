---
name: newgrain-pwa
description: "Flagleaf installable PWA (ai.flagleaf.ru/app) — one app, two tabs; phases A/B done, C/D pending"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3441be93-9176-4fd2-9061-613379401bfe
---

The agronomist web app (ai.flagleaf.ru/app) is being turned into an **installable PWA** —
chosen over native/store apps because of Russia distribution friction (App Store is hard
from RU; RuStore only covers Android) and solo-founder upkeep. Add-to-Home-Screen works on
both iPhone (Safari) and Android (Chrome), no store, no VPN. See [[newgrain-web-email-login]]
(the login it sits behind) and [[newgrain-web-ai]] (the public chat it reuses).

**Roadmap (ALL DONE):** A installable ✅ · B one app/two tabs ✅ · C offline capture ✅ · D push ✅.

**Phase D (web push):** `bot/push.py` (pywebpush + VAPID) `send_push(tg_user_id,title,body,url)` fans to
all the user's devices, prunes dead endpoints (404/410). `push_subscriptions` table (0033, keyed by
tg_user_id). VAPID keys: public in `.env` (served via `GET /api/push/key`), **private in Lockbox +
.env as `VAPID_PRIVATE_KEY`** (base64url raw 32-byte; pywebpush `Vapid01.from_string` parses it).
API: `/api/push/subscribe`, `/api/push/test`. SW has `push` + `notificationclick`. App shows a
«🔔 включить уведомления» banner (only in installed PWA where Notification/PushManager exist — iOS
16.4+ standalone only) → `subscribePush`; `ensurePushIfGranted` refreshes the sub on each open.
Trigger wired: chief-agronomist review approve/correct (bot `on_review`/`on_review_edit`) pushes the
submitter. More triggers (reminders, new-pending-for-chief) are easy follow-ons.

**Phase C (offline capture):** `web/app/index.html` queues submissions in IndexedDB (`flagleaf-q`,
store `q`; photos stored as File blobs) when `navigator.onLine` is false OR the POST fails with no
status / 5xx. A gold «Ожидают отправки» panel lists pending items; `flushQueue()` auto-sends on the
`online` event, on app entry (enterApp), and via «отправить сейчас». 4xx → dropped (won't loop);
401/403 or transient → kept. NO background sync (iOS unsupported) — flush is foreground-only.

**Built (Jun 2026):**
- `web/app/manifest.json` (standalone, gold theme, icons 192/512/maskable in web/ai/, served at root).
- `web/app/sw.js` — offline app-shell cache; `/api/*` always live; navigations network-first then
  cached tab. **Bump `CACHE` (flagleaf-shell-vN) on every shell change** or installed apps keep the old one.
- `web/app/assistant.html` — in-app AI assistant = a COPY of the public `web/ai/index.html` + manifest +
  SW + the shared header tab bar. ⚠️ Two copies now: edit BOTH when changing the assistant (unify later).
- Both pages: two-row sticky `<header>` = logo/user row (`.hrow`) + tab strip (`.tabs`:
  💬 Ассистент `/app/assistant.html` · 📷 Загрузка `/app/`). Upload page shows tabs only after login.
- Fullscreen/iOS: `header` has `padding-top:env(safe-area-inset-top)` so it clears the notch;
  status-bar meta = `default` (dark glyphs on the white header, was `black-translucent` = invisible).
  iOS caches status-bar style at install → reinstall to pick up that change.
- In-app nav buttons (‹ back / › forward / ⟳ refresh) top-left on both pages (no browser chrome in standalone).

**Deploy:** static files copied to `/var/www/ai/app/` (chmod 644); icons to `/var/www/ai/`. nginx
`location /app/` serves them — no container rebuild for front-end-only changes (only the `api` rebuilds
for backend changes). Both pages register `/app/sw.js` with `updateViaCache:'none'`.

**«Мои загрузки» panel (1 Jul 2026, Almas's ask).** Agronomists asked to confirm their own uploads actually landed (the app only showed a transient «Загружено» toast + running counts; Telegram had /history, the app didn't). Added `GET /api/my-uploads` + `db.get_user_uploads(user_id)` (caller's own recent submissions with pipeline status + is_video). New `#myUps` panel in web/app/index.html under the upload button — pulls the list from the SERVER (proof it's not just local), plain-language status (принято / ждёт разметки / на проверке у старшего агронома / размечено / отклонено), green ✅ for any on-server status, ⚠️/🚫 for warn/bad. Refreshed on login, after each photo AND video upload, and after the offline queue flushes; ⟳ button to refresh manually. SW v21→v22, announce #19. Verified: Almas (user id 2) → his real uploads with statuses. Builds on [[newgrain-motivation-no-gamification]].

**App v2 Phase 1 — the scan journey SHIPPED (2 Jul 2026).** `web/app/scan.html` (new primary tab «🔍 Определить», added across all app pages): camera-first capture → `POST /api/recognize` (NEW; wraps `diagnose._vision_sync` → structured {top, alternatives, confidence, class} for the guess card; public/IP-rate-limited like /api/diagnose) → confidence-gated guess card (≥60 «скорее всего», else «помогите определить») → tap any guess → streamed **field-grounded decision** via `/api/chat/stream` (reuse Госкаталог+ЭПВ; product+dose+timing+savings) → «Другое» text/voice (reused PCM recorder → /api/transcribe) → decision. Every choice fires `/api/submit` (photo + user's verdict as species) = the CVAT flywheel, correction=label. Field chip (/api/fields) → crop grounds recognize + decision. SW v24. **Verified on prod:** /api/recognize returns structured guesses; decision stream returns full grounded answer w/ ЭПВ. **NOT yet device-tested** (camera capture, auth'd flywheel submit, voice mic need a real logged-in phone — Almas). Realises Phase 1 of [[newgrain-app-v2-vision]] (docs/app-v2-phase1-spec.md). Announcement deliberately held until on-device UX confirmed.

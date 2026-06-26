---
name: newgrain-pwa
description: "Flagleaf installable PWA (ai.flagleaf.ru/app) — one app, two tabs; phases A–D all done; offline photo+video queue hardened (Jun 26) + RU field guide"
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
store `q`; photos AND video stored as File blobs — video items `kind:'video'` → `/api/scout-video`,
photos → `/api/submit`) when `navigator.onLine` is false OR the POST fails with no status / 5xx. A
gold «Ожидают отправки» panel lists pending items; `flushQueue()` auto-sends. 4xx → dropped (won't
loop); 401/403 or transient → kept.

**Offline-send hardening (26 Jun, `646941d`, commit `c8e4530` adds RU field guide `docs/pwa-guide-agronom.md`):**
agronomists asked "shoot offline, queue till connected" — it already existed for both media; gaps were
flush-only-while-open + video forced in-app camera. Fixes: (A) flush on `visibilitychange`/`pageshow`/
`focus` (not just `online`) = reliable cross-platform incl. iPhone; `navigator.setAppBadge(N)` shows the
pending count on the home-screen icon; **Android Background Sync** tag `flagleaf-flush` — SW `sync`
handler pings an open page to flush, else shows a "N ждут отправки" reminder (NO upload from SW — no
session token there + double-send risk). (B) dropped `capture="environment"` on `#vidFile` → video
pickable from gallery. **iPhone truth: PWAs cannot background-upload — the honest UX is "reopen the app
when back in signal"; the guide says exactly that.** Verified live (cache v19, end-to-end queue test in
preview: video blob persists in IndexedDB, panel + badge update).

⚠️ **LIVE DRIFT LESSON:** `/var/www/ai/app/` had edits never committed (демо-чат `/`→`/chat`, sw `v18`).
Before deploying web files, **diff the live URL against `git show HEAD:web/app/<f>`** and fold live-only
changes back in, or you silently regress prod. Bumped cache to **v19** (live was already a *different* v18).
Deploy = `rsync web/app/{index.html,sw.js} → /var/www/ai/app/` (newgrain-writable, chmod 644), NO rebuild.

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

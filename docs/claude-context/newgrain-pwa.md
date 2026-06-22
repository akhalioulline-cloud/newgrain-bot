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

**Roadmap:** A installable foundation ✅ · B one app/two tabs ✅ · C offline field capture ⬜ ·
D push notifications ⬜.

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

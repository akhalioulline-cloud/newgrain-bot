---
name: newgrain-web-ai
description: Public web AI demo at ai.flagleaf.ru — FastAPI on the bot VM + static chat UI (Phase 1)
metadata: 
  node_type: memory
  type: project
  originSessionId: 9edf541e-0d18-4dcd-9f29-7e993a8727e4
---

**`ai.flagleaf.ru` — public web AI agronomist (Phase 1, LIVE 2026-06-19, commits 5a66103/f484446).**
A web front-end on the SAME brain as the Telegram bot — no agronomy logic duplicated. Built to
match competitor «Андрей Тимофеевич»'s web app but better-grounded.

**Topology:** everything is on the ONE VM **111.88.248.159** (the bot VM; the marketing site's old
158.160.46.89 was stale). The VM now has a RESERVED STATIC IP (founder did it 19 Jun) — flagleaf.ru,
www, AND ai all → 111.88.248.159. nginx + certbot already served flagleaf.ru here; the bot Docker
stack also runs here.

**Backend** (`api/main.py`, FastAPI): `POST /api/chat` → `agro_chat.answer`; `POST /api/diagnose`
(multipart photo+question) → `diagnose.diagnose`; `GET /api/health`. Read-only, CORS-locked to
*.flagleaf.ru, per-IP Redis rate limits (30 chat / 8 photo per hour), input/size caps. Runs as the
**`api` service in `docker-compose.prod.yml`** (same image as bot, reuses the async DB engine), bound
to **127.0.0.1:8000**. Needs `python-multipart` (added to requirements). Deploy a change: rsync +
`docker compose -f docker-compose.prod.yml up -d --build api`.

**Frontend** (`web/ai/index.html`, repo-versioned): brand-matched (gold/Oswald/Roboto), mobile-first
single-page chat (text + 📎 photo, quick-action chips, pre-wrap for the structured emoji-header
answers). Served by nginx from **`/var/www/ai`** (owned by newgrain). Deploy: rsync repo, then
`cp newgrain-bot/web/ai/index.html /var/www/ai/index.html`.

**nginx/TLS:** vhost `deploy/ai-flagleaf.conf` → `/etc/nginx/sites-available/ai-flagleaf` (serves
/var/www/ai, proxies `/api/` → 127.0.0.1:8000, 180s timeout for the slow vision call, 15M uploads).
certbot got the cert (`sudo certbot --nginx -d ai.flagleaf.ru`), http→https redirect on. The repo
.conf is the PRE-TLS template; certbot manages the live ssl_* lines. ⚠️ Never disturb the bot Docker
stack/ports or the flagleaf.ru vhost when touching nginx.

**Phase 1 COMPLETE & LIVE (19 Jun 2026):** backend + frontend + hosting + the link from flagleaf.ru
→ ai.flagleaf.ru (gold «Попробовать ИИ-агронома» CTA in the #flagleaf section, framed under the
«скоро» badge as an early demo).

**PHASE 2 — web photo upload for labeling — COMPLETE & LIVE 21 Jun 2026** (commits 1f753e4/17e8505/
b0ca64c). Authenticated agronomist upload at **`ai.flagleaf.ru/app/`** → S3 + `submissions`, same
pipeline as Telegram but original-resolution + EXIF GPS, many photos at once. **Auth:** bot `/weblogin`
issues a 6-digit code (Redis `flagleaf:weblogin:<code>`, 5-min TTL, keyed to tg_user_id) → `POST
/api/auth/verify` → 30-day session token (Redis `flagleaf:session:<token>`) → sent as **`X-Session`
header**; `require_user` guards routes. **Endpoints** (api/main.py): `/api/auth/verify`, `/api/me`,
`/api/fields` (user's pilot fields), `/api/submit` (multipart photos[]+field_id+category+species+
comment → create_submission+update_submission; juniors role=`agronomist` → pending_review + review
cards to chiefs via a relay Bot reusing `_send_review_card`; else ready_for_labeling). GPS via
`_exif_gps` (submissions.gps_lat/lon already existed; added to update_submission allowed). **Front-end**
`web/app/index.html` (login + upload screens, drag-drop, field dropdown, category chips, species
datalist) — built by the iPhone Claude session, reviewed for consistency. KEY FIX: it sent species as
CODE; the bot stores the **Russian name** in subcategory (on_disease/on_pest → *_RU_BY_CODE) — changed
resolveSpecies to send the Russian name so web+Telegram share one vocabulary. Category CODES already
matched (weed/disease/pest/stress/control/treatment_result). **nginx:** the `/app/` + big-body (1024M,
streaming) `/api/submit` blocks were INJECTED into the live certbot-managed conf (NOT overwritten — the
repo `deploy/ai-flagleaf.conf` is the pre-TLS template; overwriting drops SSL); `.bak` kept. GOTCHA:
iCloud-downloaded file was perms 600 → nginx 403; needs **644**. Phase 3 ideas: «Мои загрузки» gallery,
voice comment, web review UI for the chief.

**Phase 1.5 features shipped 20 Jun 2026** (commit 2554e3c): (1) **crop selector** (🌱 dropdown) →
sent to both endpoints (`crop` field; chat prepends «Культура: X.»), skips «какая культура?».
(2) **Per-answer buttons** 📋 copy / 👍 / 👎 / 🧮, like the competitor; removed the quick-action chips
(cramped on mobile). (3) **Follow-up memory** — client keeps `history[]`, sends last 6 turns to
`/api/chat`; `answer(question, context, history)` gained a `history` param (additive). Photo
diagnoses go into history too → text follow-ups keep photo context. (4) **🧮 dosage calculator** —
appears only when the answer has product norms (regex on л/га|норма|препарат); asks hectares →
sends a «рассчитай из предыдущего ответа на N га» follow-up the LLM computes from history (verified:
0,04 кг/га×50 = 2 кг + 200 л/га×50 = 10000 л). (5) **Richer 👎** → optional «что не так?» note →
`web_feedback.note`. (6) **Voice 🎤** — browser Web Audio (ScriptProcessorNode) captures, downsamples
to 16 kHz mono **Int16 LPCM**, POSTs raw bytes to **`POST /api/transcribe`** → `transcribe.transcribe_lpcm`
→ Yandex SpeechKit (format=lpcm). Browsers can't easily emit OGG/Opus, hence LPCM; no Whisper model in
the api. **`web_feedback` table** (migrations 0029+0030: vote/crop/question/answer/note/ip) — anonymous
answer-quality signal (NOT analytics; spec §3.3 ok). The api now has ONE DB write (feedback); still
no field data exposed. Voice CONFIRMED working (founder tested 20 Jun); ScriptProcessor is
deprecated-but-works incl. iOS Safari (needs HTTPS + mic permission).

**Phase 1.5b shipped 20 Jun 2026** (commit 4b3c0b8): (7) **📤 Share** button (next to 📋, same .act
style) — `navigator.share` native sheet on mobile, clipboard fallback on desktop. (8) **«Связаться с
агрономом»** — gold pill button above the disclaimer opens a modal lead form (имя/телефон/вопрос) →
**`POST /api/contact`** → `web_leads` table (migration 0031) AND Telegram push to ADMIN_TG_IDS via
`labeling.alert.send` (sync helper, called off-thread via asyncio.to_thread; routes through the
TELEGRAM_API_BASE relay). DB row is the durable record (`notified` flag) if the ping fails. Phone
required (light validation), 10/h per IP. The api now imports `labeling.alert` + `asyncio`. Founder
chose the form-→-Telegram option over public contact links (no personal info exposed).

Phase 2 (later): real auth, field context from the user's actual fields, tank-mix compatibility +
weather «можно ли обрабатывать сегодня» (HELD — need vetted data, safety risk).

**Marketing site editing** (the CTA lives here): `flagleaf.ru` site = `/var/www/flagleaf` on the
bot VM, **NOT in git** — local working copy at `~/flagleaf-site` (pull: `rsync -az
newgrain@111.88.248.159:/var/www/flagleaf/ ~/flagleaf-site/`). Bilingual: RU in `index.html` on
`data-i18n` keys, EN in the `EN={}` dict in `assets/js/main.js` (same keys) — edit BOTH. Deploy:
`rsync -az --exclude '*.md' ~/flagleaf-site/ newgrain@111.88.248.159:/var/www/flagleaf/` (static,
instant; verify `curl -sI https://flagleaf.ru` → 200). Brand tokens in `style.css :root` (gold
#b9994b, Oswald/Roboto). The site's own CLAUDE.md/INFRASTRUCTURE.md (in founder's iCloud Downloads)
have stale IP 158.160.46.89 — real VM is 111.88.248.159.

Spec: `docs/web-phase1-spec.md`. See [[newgrain-prod-deploy]], [[newgrain-roles-review-gate]] (brain).

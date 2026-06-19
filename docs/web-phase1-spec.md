# Phase 1 spec — flagleaf.ru AI web chat

*A public web version of the bot's AI agronomist — text Q&A + photo diagnosis — reusing the
existing brain. No CropWise-like screens (fields/calendar); just the chat, with room for
quick-action buttons later. Mobile-first, like ai.agrotochka.org but better-grounded.*

## 0. The key fact that drives the design

The valuable logic — **the brain — is already built and channel-agnostic**: `bot/agro_chat.py`
(structured Q&A), `bot/diagnose.py` (photo diagnosis), the Госкаталог grounding, crop-safety
rules, CyberLeninka citations. A web app is just a **new front-end on the same brain**. We do
NOT rebuild any agronomy logic.

**Topology (two VMs):**
- **Marketing site** `flagleaf.ru` → VM `158.160.46.89` (nginx + certbot, stable, has the domain).
- **Bot brain + Postgres + LLM keys** → VM `111.88.248.159` (Docker stack; ephemeral public IP).

The chat API must run **where the data/brain/keys are** (the bot VM). So Phase 1 is a
**self-contained AI app at `ai.flagleaf.ru`, hosted on the bot VM**, and the marketing site
simply links to it ("Попробовать ИИ-агронома"). This avoids cross-VM DB access and keeps the
two concerns cleanly separated.

```
 user browser
   │  https://ai.flagleaf.ru
   ▼
 Bot VM 111.88.248.159  (Docker: postgres + redis + bot)   ← add:
   ├─ nginx + certbot (ai.flagleaf.ru, TLS)                ← new
   ├─ static chat UI  (/var/www/ai or served by FastAPI)   ← new
   └─ FastAPI (api/)  → reuses agro_chat / diagnose / db    ← build out the existing stub
 flagleaf.ru (158.160.46.89) — marketing site, just adds a link to ai.flagleaf.ru
```

## 1. Scope (Phase 1)

IN: mobile-first chat page; text agronomy Q&A; photo + question → structured diagnosis;
the structured/grounded answers we already produce (named registered products, producer tags,
safety caveats, citations); a short "проверяйте перед применением" disclaimer.

OUT (Phase 2+): login/accounts, field data, calendar, operation logging, history, the
"useful buttons" (ideated later), answer streaming, multi-language.

## 2. Backend — build out `api/` (FastAPI, already a dependency)

Reuse the brain directly (same process, same async DB engine). Endpoints:

- `POST /api/chat` — `{ "question": str, "session": str }` → `{ "answer": str }`
  - wraps `agro_chat.answer(question)` (no field context in Phase 1).
- `POST /api/diagnose` — multipart `image` + `question` + `session` → `{ "answer": str }`
  - wraps `diagnose.diagnose(img, question, crop=None, field_name=None)`.
- `GET /api/health` — liveness (exists).

Rules: read-only (no DB writes, no secrets, no field data exposed); input caps (question ≤ 1–2k
chars, image ≤ ~8 MB, downscale server-side before the vision call); per-IP + per-session rate
limit (e.g. 20 questions / 5 photos per hour) since each call costs LLM money; CORS locked to
`https://ai.flagleaf.ru` (and `flagleaf.ru`). Runs as a new service in `docker-compose.prod.yml`
(the `api` service, currently unused) bound to localhost; nginx terminates TLS and proxies to it.

## 3. Frontend — static chat page (brand-matched, no build step)

Plain HTML/CSS/JS to match the marketing site's stack (Oswald/Roboto, gold `#b9994b`/black/white).
A single mobile-first chat screen: message bubbles, text input, 📎 photo attach, send, "анализирую
фото…" states, render the structured answer (the emoji-header sections already read well as plain
text). A row of **quick-action chips** as placeholders for the Phase-2 buttons (определить по фото /
чем обработать / …) — wired later. Served by nginx on the bot VM at `ai.flagleaf.ru`.

## 4. Auth & abuse control (Phase 1 = open demo, lightly gated)

No login (matches agrotochka; best for a public/marketing demo and the Skolkovo angle). Guard cost
& abuse with: per-IP + per-session **rate limits**, input/size caps, and a lightweight abuse check
(e.g. Yandex SmartCaptcha or a simple challenge if traffic warrants). Real auth (phone/SMS or
magic-link) is **Phase 2**, only if it becomes the working agronomists' tool rather than a demo.

## 5. Hosting / DevOps (one-time setup)

1. **Reserve a static IP for the bot VM** (Yandex Cloud console). This both enables a stable
   `ai.flagleaf.ru` A-record AND fixes the long-standing ephemeral-IP deploy pain (the deploy
   script's `SERVER` IP moves whenever the VM restarts). *Founder action — Yandex console.*
2. **DNS** (reg.ru): `A  ai → <bot VM static IP>`. *Founder action.* (No AAAA, per the site rule.)
3. **Security group:** open inbound **443** (and 80 for the ACME challenge) on the bot VM.
   *Founder action — Yandex console.* (Today the bot VM exposes no ports.)
4. **nginx + certbot** on the bot VM for `ai.flagleaf.ru` → reverse-proxy to the FastAPI container.
   *Claude — coexists with Docker, never touches the bot's ports/firewall internals.*
5. **Marketing site:** add a button/link on `flagleaf.ru` → `https://ai.flagleaf.ru`. *Claude,
   in the website repo.*

⚠️ Hard constraint (from the site docs): **never disturb the bot's Docker stack, ports, or
firewall** while adding nginx. nginx + Docker coexist on the VM; we only add an nginx vhost +
a localhost-bound API container.

## 6. Security & safety

- The brain already refuses crop-killing/unsafe advice and grounds in the Госкаталог — the public
  demo inherits that. Keep the "ИИ-помощник, проверяйте перед применением" disclaimer visible.
- API surface is chat+diagnose only; no farm data, no writes, no creds. Secrets stay in `.env`.
- Rate-limit + caps bound LLM cost (each query ≈ a few kopecks of YandexGPT/qwen).

## 7. Effort & sequence

| Step | Work | Owner | ~Effort |
|------|------|-------|---------|
| 0 | Reserve static IP, `ai` DNS, open 443 | Founder (console/DNS) | ~30 min |
| 1 | FastAPI `/api/chat` + `/api/diagnose` (reuse brain) + rate limit | Claude | 2–3 days |
| 2 | Static chat UI (brand-matched, mobile-first) | Claude | 3–5 days |
| 3 | nginx + certbot on bot VM, wire `ai.flagleaf.ru`, CORS | Claude | 1–2 days |
| 4 | Link from flagleaf.ru | Claude | <1 day |
| — | **Total** | | **~1.5–2 weeks** |

## 8. Decisions needed from the founder

1. **Subdomain:** `ai.flagleaf.ru` (recommended) for the app.
2. **Reserve a static IP for the bot VM** — yes? (recommended; also fixes deploy stability).
3. **Auth posture:** open rate-limited demo (recommended) vs. a gate from day 1.
4. **Confirm topology:** are the bot (111.88.248.159) and site (158.160.46.89) truly two VMs?
   (Step 0 hosting depends on it; quick check in the Yandex console.)

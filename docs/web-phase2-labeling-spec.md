# Web Phase 2 — agronomist photo upload for labeling

**Status:** spec / not built. **Author:** Claude, 2026-06-20. **Decided by:** founder.
See [web-phase1-spec.md](web-phase1-spec.md) for what's already live, and the memory
`newgrain-web-ai` for topology.

## 1. The gap this closes
Today **only the Telegram bot collects labeling data**: a photo there is saved to Object
Storage + written to `submissions` (`ready_for_labeling`) → CVAT → the future CV model. The
**web (ai.flagleaf.ru) does not** — a web photo is diagnosed and thrown away (the api is
deliberately public + read-only, writing only feedback/leads).

This phase lets a **logged-in agronomist** upload photos *for labeling* from the web — the same
data asset the Telegram flow produces, but with the web's advantages.

## 2. Guardrail (Г1: build to learn, not to scale)
This is a **complement to Telegram, not a replacement.** Telegram stays the default, low-friction,
in-the-field channel. The web upload earns its keep only where it's genuinely better:

- **Desktop / bulk** — drag-and-drop *many* photos at once from a laptop (Telegram is one-at-a-time).
- **Original quality + EXIF GPS** — browsers can send the *original* file; Telegram pre-compresses
  and strips EXIF, so the Telegram path **loses GPS and resolution**. Web upload can keep both →
  richer metadata for training (where in the field, full detail).
- **Manage your submissions** — a gallery of what you've sent and its status (later phase).

If none of those matter for a given user, they should just keep using Telegram. We do **not**
duplicate Telegram wholesale.

## 3. What the agronomist does (target flow)
1. Open `ai.flagleaf.ru` → **«Войти»** (see §5 auth). One-time, session persists ~30 days.
2. Tap **«Загрузить для разметки»**.
3. **Pick the field** (dropdown of *their farm's* pilot fields; + «Другое поле» = off-pilot, like
   Telegram's field_id=None).
4. **Drop one or many photos.**
5. For the batch: **category** (сорняк / болезнь / вредитель / …) and **species** (searchable list
   + «Другой» free text — same dictionary as Telegram). Optional **comment** (text; voice later).
6. **Submit** → each photo → Object Storage + a `submissions` row (`ready_for_labeling`), exactly
   like Telegram. Confirmation with a count.
7. If the uploader is a **junior**, the batch goes `pending_review` and a review card is sent to the
   **chief agronomist** (Almas) — the *existing* review gate, unchanged (he can approve in Telegram).

## 4. Why it's mostly reuse (low agronomy risk)
The backend already has every save primitive — the api shares `bot.db` + `bot.storage`:
- `bot.storage.upload_bytes(key, data, mime)` — store the photo.
- `bot.db.create_submission(id, user_id, field_id, image_url, w, h, …)` — the row.
- Fields per farm: `SELECT id, name, crop, area_ha FROM fields WHERE farm_id=:f AND is_pilot`.
- Review gate: `get_chief_agronomists(farm_id)` + `_send_review_card` + `pending_review`.
So §3 is *wiring*, not new agronomy logic. The genuinely new parts are **auth** and the **upload UI**.

## 5. Authentication (the crux — pick one, §11)
The web is anonymous today; labeling writes farm data, so we must know **who** is uploading and tie
them to their `users` record (tg_id, role, farm_id). Three options:

- **A — Bot-issued one-time code (RECOMMENDED).** On the web, "Войти" asks for a code; in Telegram
  the agronomist taps `/weblogin` and the bot replies with a 6-digit code (5-min TTL in Redis,
  keyed to their tg_id). They enter it on the web → the api verifies → issues a signed session
  cookie tied to their user record. **Why:** reuses the existing whitelist, no passwords, no
  external service, and it works *through the Telegram relay* we already run despite the RU block.
- **B — Telegram Login Widget.** Official, slick, but needs bot-domain config and the widget JS,
  which is awkward/iffy under the RU Telegram block. More moving parts.
- **C — Password / magic-link.** Familiar but adds a credential to manage and an email/SMS sender we
  don't have. Most work, least leverage of what we already have.

## 6. Backend changes (`api/`)
Add an **authenticated** surface alongside the public demo (keep them separate; public routes stay
read-only):
- `POST /api/auth/start` + `/api/auth/verify` (option A: code → session). Session = signed cookie or
  JWT, Redis-backed, ~30-day TTL. A lightweight `require_user` dependency for protected routes.
- `GET /api/me` — who am I (name, role, farm).
- `GET /api/fields` — the user's farm pilot fields.
- `GET /api/species` — the category/species dictionary (for the picker).
- `POST /api/submit` — multipart: photos[] + field_id + category + species + comment. Loops photos →
  `upload_bytes` + `create_submission`; applies the review gate for juniors. Returns counts.
- New bot command **`/weblogin`** (issues the code).
- **EXIF GPS + original resolution:** read EXIF from the uploaded file server-side, store lat/lon on
  the submission (needs a small `submissions` column add via migration if not present), keep a
  reasonable max resolution (no aggressive recompress like the diagnosis path).

## 7. Frontend (`web/`)
A second, gated screen (the public chat stays as-is):
- **Login** screen (code entry).
- **Upload** screen: field dropdown, multi-file drop zone with thumbnails + per-file remove,
  category buttons, species search-select (+ «Другой»), comment, a Submit with per-file progress.
- **(Phase 2b)** «Мои загрузки» gallery: your submissions + status badges.

## 8. Phasing
- **2a (MVP):** auth (option A) + single-screen multi-photo upload → `submissions`, review gate
  reused, EXIF GPS captured. This delivers the core value.
- **2b (later):** submissions gallery + status, voice comment, edit/delete, web review UI for the
  chief, bulk CSV-style metadata.

## 9. Effort & risk (rough)
- **Effort:** medium — a few focused sessions. Auth + session (~1), `/api/submit` + fields/species
  (~1), upload UI (~1–2). Most save-logic is reuse.
- **Risk:** low-moderate. The new risk is **auth on a write surface** — must be solid (only
  whitelisted agronomists can write farm data; sessions scoped to one user/farm; rate-limited;
  public demo routes untouched). No agronomy-correctness risk (reuses the proven save path).

## 10. Non-goals (for now)
Public/anonymous labeling upload (quality + trust — labels must come from known agronomists);
replacing Telegram; in-web CVAT/annotation (annotation stays in CVAT).

## 11. Decisions (locked by founder, 2026-06-20)
1. **Auth method** — ✅ **A: bot-issued one-time code** (`/weblogin` → 6-digit, Redis TTL → session).
2. **Driving need** — ✅ **Both** desktop/bulk upload **and** original-resolution + EXIF GPS. So 2a
   includes multi-file drag-drop AND server-side EXIF GPS capture + a `submissions` lat/lon column.
3. **Who can upload** — ✅ **All whitelisted agronomists** from the start (gated by login; juniors
   still go through the review gate).
4. **Species at upload** — default: **required, same as Telegram** (dictionary + «Другой»); revisit
   if it proves to add friction.

### Build order (2a)
1. `/weblogin` bot command + `POST /api/auth/start|verify` + session middleware (`require_user`).
2. `GET /api/me`, `GET /api/fields`, `GET /api/species`.
3. `POST /api/submit` (multi-photo + metadata → `upload_bytes` + `create_submission` + review gate);
   EXIF GPS read + `submissions` lat/lon migration; keep original-ish resolution.
4. Web: login screen + upload screen (field, drag-drop, category, species-search, comment, progress).

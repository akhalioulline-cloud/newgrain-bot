# Phase 1 build spec — the re-pointed journey (first testable version)

*Goal: turn "a tool they feed" into "a tool they use." Put a delightful capture → guess →
**field-grounded decision** flow in front of Almas and measure two things: does it beat his
brain on the decision, and is it nice enough to open. Web app first (native = Phase 2).*

---

## What we're testing (MVP scope)
Capture a weed → get a confidence-gated guess → tap → the streamed decision (product + dose +
ЭПВ timing + ₽ savings for *this* field) → "Other" corrects it by voice/text → the photo +
the user's verdict silently feed the CVAT flywheel.

**Out of this MVP** (later phases): Capacitor native shell (P2), offline (P3), live AR species
label + framing reticle (P4 — MVP uses the native camera + a simple quality hint), social (P5).
Recognition runs on **qwen (in-RU)**; the custom model is the parallel Track A.

---

## Screen flow → endpoints (new vs reused)

| # | Screen | What it does | Endpoint | New / Reused |
|---|---|---|---|---|
| 0 | Entry | One big "Определить" → opens camera | app shell / `/api/me` | Reused |
| 1 | Camera | Native camera capture; **field chip** (grounds the decision) | `/api/fields` | Reused |
| 2 | Analysing | Slick loader while qwen runs | **`/api/recognize`** | **NEW** (thin wrapper) |
| 3 | Guess card | Top guess + confidence + type; 1–2 alts; "Другое" | *(client renders step 2)* | — |
| 3b | "Другое" | Voice/text: "what is it?" | `/api/transcribe` | Reused |
| 4 | **Decision (reward)** | Streamed product + dose + ЭПВ timing + ₽ savings | `/api/chat/stream` | Reused |
| — | Flywheel (bg) | Log photo + the user's verdict as the label | `/api/submit` | Reused |

**So the only new backend is one endpoint.** The rest is front-end assembly of the diagnose /
chat / voice / submit engines already in production.

---

## The one new endpoint: `POST /api/recognize`
Wraps the vision dict `diagnose._vision_sync()` already computes internally (but `/api/diagnose`
currently hides behind a text blob). Returns structured candidates for the guess card.

```
POST /api/recognize   (multipart: image, crop?)
→ vd = diagnose._vision_sync(image)          # existing qwen call, structured
→ 200 {
    "top":        {"latin": vd.latin, "ru": vd.diagnosis, "confidence": vd.confidence,
                   "class": vd.weed_class, "category": vd.category},
    "alternatives": vd.differential,          # [{name, why}, ...]
  }
```
- Rate-limited like `/api/diagnose`; reuses `_prep_image` downscale + the brevity directive.
- **Confidence gating is client-side:** conf ≥ 60 → "Скорее всего: X"; conf < 60 (or a
  differential present) → "Не уверен — помогите определить" and lead with alts + "Другое".
  (Never present a low-confidence guess as fact.)

---

## The decision (Screen 4) — reuse `/api/chat/stream`
On any choice (top / alt / declared), call the streamed chat with the chosen weed + field crop:
```
POST /api/chat/stream  { question: "Чем обработать {crop} от {weed}? Пора ли по ЭПВ? Норма? Сколько обработок?",
                         crop: "{crop}" }
```
Already grounded in Госкаталог + Almas's ЭПВ + streaming (built this week). The UI just renders
the token stream into the reward card + a "План по полю" button (`/api/plan`).

---

## The flywheel (background) — reuse `/api/submit`
At the moment of choice, POST the retained photo bytes with the user's verdict as the label:
```
POST /api/submit  (image, field_id, category="weed", species="{chosen or declared}")
```
- The **correction is the label** — best-quality ground truth, harvested from real use.
- Chief review still applies for juniors (existing gate); Almas's own → straight in.

---

## Task breakdown (implementation order)
1. **Backend** — `POST /api/recognize` (thin wrapper over `_vision_sync`); return structured JSON. *(small)*
2. **Frontend scaffold** — a new scan flow (route `/app/scan.html` or a mode in the app): states camera → analysing → guess → decision, with the existing auth/session helper.
3. **Recognise → guess card** — render top + alts + confidence gating.
4. **Tap → decision** — reuse the `/api/chat/stream` reader (from the assistant) to stream the reward card; add "План по полю".
5. **"Другое"** — mic (`/api/transcribe`) / text → decision for the declared weed.
6. **Flywheel** — on choice, `/api/submit` with photo + verdict; keep photo bytes from capture.
7. **Field grounding** — field chip (reuse `/api/fields`), default last-used; crop flows into recognise + decision.
8. **Delight pass** — camera→card transition, slick "анализирую" loader, reward reveal, "+1 обучает ИИ" cue. No points/badges.
9. **Test with Almas** — does it beat his brain + feel good.
10. *(fast-follow, still P1)* framing/quality hint overlay (accuracy lever).

---

## Decisions I need from you
- **Confidence threshold** for "present as fact vs help-me-identify" — default **60**, tunable.
- **Field grounding default** — last-used field chip is simplest for MVP (geo-detect later). OK?
- **Log every photo** (all are training data) with the confirmed/corrected label — yes (recommended).
- Where it lives — a **new tab/screen "Определить"** alongside Загрузка/Ассистент, or replace the current upload-first screen? (I'd add it as the new primary entry, keep the others.)

---

## Why this is fast
The expensive half — recognition (qwen), the grounded decision (`agro_chat` + Госкаталог + ЭПВ +
streaming), voice, the flywheel — is all in production. Phase 1 is **one new endpoint + a new
front-end flow** that re-points those engines at the reward. That's what makes it the highest-ROI
move and a genuine first testable version.

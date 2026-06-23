---
name: newgrain-pilot-v2
description: "Pilot v2 pivot: from weed-photo volume to field treatment-PLANS + measured chemical savings"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3441be93-9176-4fd2-9061-613379401bfe
---

**Strategic repositioning (Jun 2026, founder-driven).** Pilot v1 ("agronomist uploads 15–30
photos/wk") was breaking: as fields get sprayed clean there's nothing to shoot, and single-photo
weed-ID is a commodity feature (vs Gemini), not a product. Founder reframed the product as the
**decision loop**: sense field → produce/update a treatment PLAN → execute via CropWise/machines →
observe → revise. The moat = closed loop on a field over time + local registered-products + execution
link (a general vision model has none of these). Recognition is one *sensor*, not the product.

**New pilot formula:** data unit = a **scouting pass that covers the whole field (clean areas
included — "where NOT to spray")**, not hero photos. Success metric = **measured chemical/cost saving
of the plan vs the blanket spray actually applied** (CropWise has the real spray records), on 1–2
fields. Current work isn't thrown away — photos/recognition = perception layer; CropWise op-logging =
execution+history; new field-plan generator = decision layer. See [[newgrain-pwa]], [[newgrain-oplog-freetext]].

**Built (commit 245e56f):**
- **`bot/field_plan.py` + `/plan <field>`** (bot command, in menu): grounds an LLM (agro_chat._complete /
  YandexGPT) on `field_card_text` (history/NDVI/catalog) + `get_field_observations` (recent scouting,
  with GPS) + `get_registered_products` (Госкаталог). Structured output: 🗺 состояние · 🎯 где
  обрабатывать/где НЕТ · 💊 план (registered products + norms + machine + timing) · ♻️ экономия химии ·
  ⏭ что обследовать. Enforces crop-safety + registered-only. Verified live on field 121/140 (Соя) —
  produces a real grounded plan; honestly says it needs full-field scouting/drone for the savings MAP.
- **Scouting capture in the app**: new category `scouting` («🔍 Обследование поля») — captures the whole
  field incl. clean areas (GPS kept), no per-object species. `CATEGORY_LABELS["scouting"]` set for /history.
- **`docs/pilot-v2-onepager`** (HTML+PDF): the repositioning, for team alignment.

**Roadmap:** NOW = /plan on existing data + scouting capture + quantify plan-vs-blanket saving on 1–2
fields. NEXT = one contracted drone flight (field-scale sensing proof, manual analysis, no pipeline).
LATER = versioned per-field plans that update each pass + measured efficacy (the real moat).

**In the app (done, commit afcb5ef):** `/api/plan` (auth, farm-scoped) wraps generate_field_plan; the
assistant tab has a «📋 План по полю» button → asks the field → renders the plan (reads `flagleaf_session`
from localStorage, sends X-Session). **Savings grounded in CropWise:** `get_field_protection_baseline`
pulls the season's blanket protection passes (product/dose/area_ha/cost — note: dose & cost are TEXT, no
numeric rate); the plan header shows "Сплошных обработок СЗР в сезоне N: K (база)" and the ♻️ section
compares the targeted plan to that real spend. The exact saving % stays an honest estimate until scouting
gives spatial coverage (GPS passes) — the model says so itself. Verified: field 121/140 = 7 blanket passes/2026.

**Ruble savings (done, commit d8640c6):** `product_prices` table (0034) + `/setprice Назв = 1200 л` and
`/prices` (admin). `field_plan.parse_dose` (мл/л/г/кг → л|кг) × area × price → deterministic ₽ baseline in
the plan header + ♻️ section. Prices are founder-supplied (never invented); plan computes ₽ only for
priced+parseable passes, stays qualitative otherwise.

**FIRST LOOP set up — field = Поле 39 · Красное (Соя, 113 га):** chosen data-drivenly (8 blanket passes
this season + 19 scouting observations — the richest). This-season baseline = 2 spray dates (15.05, 11.06)
× 4 products → applied volumes: Трейсер 67.8 л, Когорта 452 л, Алсион ВДГ 1.808 кг, Адью Ж 45.2 л.
**Pricing shortlist = those 4 products** — founder runs /setprice for each, then ₽ baseline computes.
Runbook: scout Поле 39 (app «Обследование поля», whole field incl. clean, GPS) → /plan Поле 39 → review
plan-vs-blanket saving (Almas). The saving % still needs GPS scouting coverage to firm up.

**Savings-log (done, commit a4b2053):** `plan_runs` table (0035) — every /plan (bot or app) logs
field/season/baseline_passes/baseline_cost(₽ when priced)/plan_text/ran_by. `/savings` (admin) lists recent
runs; `/savings Поле 39 = точечно, экономия ~30%` records the realized outcome on the latest run for a field.
(asyncpg note: nullable-param `(:x IS NULL OR ...)` throws AmbiguousParameterError — build the WHERE
conditionally instead.) First entry logged: Поле 39, база 8 обр.

**Scouting photo flow (commit 178b499):** app «🔍 Обследование поля» (category=scouting) → /api/submit →
original to S3 (newgrain-data-prod) + EXIF GPS + submissions row → **excluded from CVAT export**
(`category IS DISTINCT FROM 'scouting'`) → read directly by /plan via get_field_observations. Scouting is
**app-only** (bot photo flow has no scouting category yet). **Videos: not supported** (app accept=image/*;
bot=photos) — that's the drone/video phase. Diagnostic photos still go through CVAT (recognition) as before.
**Evgenia (tg 5872820319) made admin via ADMIN_TG_IDS on prod .env** (kept her annotator role so pipeline
notifications still reach her) → can run /setprice /prices /savings. See [[newgrain-roles-review-gate]].

**Scouting review-bypass + Telegram (commit 4e1f9e1):** scouting now skips the junior review gate in BOTH
/api/submit (is_scouting → review=False) and the bot `_finalize` (category=='scouting' → ready_for_labeling,
no card). Scouting category added to the bot photo keyboard (CATEGORIES, last) → on_category else-branch
(no species) → comment (voice ok). Bot scouting is per-photo (app better for multi-photo passes).

**Video scouting — BUILT & verified end-to-end (commit d0c846d).** App scouting mode → «🎥 Видео
обследование» (≤3 min, client-side size+duration pre-check, offline-queued like photos, kind='video' →
/api/scout-video). `/api/scout-video` stores the video to S3 → creates a scouting submission (bypasses
review) → `video_jobs` queue (migration 0036). Background collector `labeling/video_collect.py` (cron
**every 5 min**) downloads the video → `bot.video_transcribe.transcribe_video` → writes narration to the
submission's `comment_voice_text` (which /plan reads). **Transcription = ffmpeg splits audio into ≤25s
chunks → SYNC SpeechKit per chunk** (NOT the long-audio API: longRunningRecognize 403'd fetching audio
from our private bucket — the API-key's SA lacks bucket read; chunked-sync sidesteps OS entirely + reuses
the proven voice-note path). ffmpeg added to the image; nginx 512M body on /api/scout-video (injected into
live conf, certbot-managed). Verified: real speech mp4 → "На поле 217 очаги заразихи у южной кромки…".
Caps: app 3 min / 185 s, backend MAX_VIDEO=400 MB, nginx 512 M. Frame extraction (visual field-state) still
a later phase. Earlier assessment below superseded.

**[superseded] Video scouting — ASSESSED, not built (key constraint).** Transcription is Yandex SpeechKit SYNC
(transcribe.py) = **≤30 s / ≤1 MB** — fine for short clips, NOT full field-walk narrations. faster-whisper
was removed (RAM). Also no ffmpeg in the image (needed to extract a video's audio track). Recommended phasing:
V1 = short narrated clips (≤~25s): app video input → new /api/scout-video → ffmpeg extract audio → SpeechKit
sync → transcript = scouting observation; video to S3 (raise 25MB cap). V2 = long video via SpeechKit ASYNC
long-audio (reads audio from Object Storage, poll). Frame extraction (visual field-state) = separate later
phase. Flag: video storage grows S3 fast. Awaiting founder go on V1.

**Scouting session mode + voice comment (commit e0b8a9a).** App: «🔍 Режим обследования поля» checkbox
locks category='scouting' across submissions (hides #catPick, persisted in localStorage 'scoutMode',
restored in enterApp). Bot: `/scout` toggles a 12h Redis session (flagleaf:scoutmode:<tg>); `_save_photo_for_field`
checks `_scout_mode_on` → auto-tags scouting + skips the category step → comment. **Voice comment in the app:**
🎤 on the photo comment (cmtMic) — same Web Audio→16k LPCM→/api/transcribe flow as the assistant mic, inserts
into #comment. (App photo comment was text-only before; bot already had voice via the comment step.) The
scouting↔diagnostic fork is the CATEGORY choice (explicit, not auto-detected); everything downstream keys off
category=='scouting' (skip species, skip review, skip CVAT export, feed /plan).

**Fields opened + demonstration fields + motivation panel (commit 1222e6a, migration 0037).** All 286
real fields (single farm) now `is_pilot=true` (agronomists report whatever field they're on — no wasted
travel). The original 12 pilots kept as **`is_demo`** = "контрольные/demonstration fields" (the ones to
scout regularly for the savings proof). App: field picker is now a **searchable datalist** over all 286
(type a number; demo fields marked ⭐); `currentFieldId()` resolves name/number → id. **Motivation UI
(built):** «🎯 Контрольные поля» panel (`/api/demo-fields` → get_demo_fields w/ last-observed recency) —
color dot **green ≤7d (weekly cadence) / amber 8–10 (grace) / red >10 or never**, "N дн. назад", tap →
preselect field + scouting mode. **Red-field push nudge** (commit 6a0bd64): `labeling/field_nudge.py`
(daily cron 08:00) pushes whoever LAST scouted a red demo field «вы давно не были на Поле … (N дн.)»,
throttled 4d per user/field (Redis flagleaf:fieldnudge:tg:fid); needs push enabled (≈0 until agronomists subscribe). Recognition/nudge, NOT points (consistent with
[[newgrain-motivation-no-gamification]]). Bot keeps a 12-button quick-pick (`get_demo_field_list`) +
«Другое поле» → any of 286 by number (`find_fields_by_number` searches all fields). /fields shows control fields.
Decision rationale: opening = breadth (engagement + recognition variety); is_demo preserves DEPTH for the
savings demo. NOT done: full CropWise refresh to ~443 (the ~157 missing are archived/old-season; tooling
exists — catalog/ingest_fields.py + scripts/cropwise-sync.sh — run if a field doesn't resolve).

**Open/next:** founder prices the 4 Поле-39 products via /setprice; scout Поле 39; /plan; Almas reviews;
/savings to log. Frame extraction (video visuals → zone data) still the later drone phase.

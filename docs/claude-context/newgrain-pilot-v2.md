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

**Open/next:** as GPS scouting accumulates, tighten the saving % into a real figure (treated-area fraction);
Almas should review the first generated plans (human-in-loop is the point); consider per-product price table
for ruble savings (cost field is unreliable text today).

---
name: newgrain-roles-review-gate
description: "Bot roles + the chief-agronomist review gate on junior agronomists' photo submissions"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4de747c7-0a5d-470a-b9b0-bdb18bbd3c95
---

Bot roles (users.role) as of 2026-06-17: **admin** (Алексей Халиуллин id1, Алексей
Ефременко id5, Алексей Дурнев id8 tg 5425284392 — migration 0024), **chief_agronomist**
(Алмас Касумов id2, tg 1895200085 — migration 0022), **annotator** (Евгения Снеговская id7,
tg 5872820319 — migration 0023), **agronomist** (Сорока, Костенников, Швец-Ковган).
ADMIN_TG_IDS (server .env, non-secret): 417450813,1889637036,5425284392. Full admin =
DB role 'admin' AND tg in ADMIN_TG_IDS (the review-gate check uses DB role; the command
menu + /problem recipients use ADMIN_TG_IDS) — set both when promoting an admin.

**annotator role:** annotation happens in CVAT, not the bot, so the role's ONLY bot
behaviour is to RECEIVE the labeling reference sheet + «батч готов» notice — `reference.py
--deliver` fetches photos + annotator ids in ONE event loop and passes them via
`alert.send(extra_ids=annotator_ids)` (error/ops alerts stay admin-only). **Bugfix 19 Jun:**
the old path used a SECOND `asyncio.run` (alert._annotator_ids→get_annotators) that reused the
async DB engine bound to the first closed loop → "attached to a different loop" → annotator
lookup silently failed → the sheet reached ADMINS ONLY for weeks (Евгения never got it). Fixed
via same-loop fetch + `extra_ids`; verified delivery to 4 incl. 1 annotator. The 03:30
pipeline.sh cron uses the same path, so future batches reach annotators too. Not a data collector → the
agronomist→CA review gate doesn't apply. (CVAT itself: Евгения uses the founder's CVAT
login for now — recommend her own membership in the NewGrain CVAT org instead.)

**Review gate (live 2026-06-17):** a junior **agronomist**'s finished photo submission
goes to `status='pending_review'` and a review card (photo + all attributes) is forwarded
to the chief agronomist(s); it does NOT enter the labeling pipeline until the CA approves.
chief_agronomist + admin post straight to `ready_for_labeling` as before (workflow
unchanged for them). The CA edits any attribute inline (field/species/category/comment);
**a correction itself finalizes the photo → `ready_for_labeling` immediately** (no extra
confirm), and the junior is only NOTIFIED of the change (never re-confirms). ✅ handles
the no-correction-needed case → `ready_for_labeling` + junior notified accepted. If no CA exists, junior photos fall through to ready_for_labeling
(no stranding). **BUGFIX 19 Jun (commit d43cb2c):** `get_chief_agronomists` used
`(:f IS NULL OR farm_id=:f)` → asyncpg AmbiguousParameterError EVERY call → `_finalize` set
pending_review then crashed before sending the card → Almas got NOTHING and ~20 junior photos
(Сорока, Швец-Ковган) stranded. Fixed (conditional farm filter); re-delivered the 20-card backlog
to Almas via a one-off relay-Bot + `_send_review_card`. (2nd silent-delivery bug after the annotator
cross-loop one — watch async-DB param typing + multi-`asyncio.run`.) Almas IS reachable (getChat 200). Code: `_finalize` role-branch, `_send_review_card`/`_review_kb`/`on_review`
+ `CAReview.editing` text handler in handlers.py; `get_chief_agronomists`/
`get_submission_review` in db.py; `update_submission` now allows `field_id`. New status
label `pending_review` = «на проверке у старшего агронома». IN FIELD TESTING.

**Agronomist Q&A chat (LIVE 17 Jun 2026):** `bot/agro_chat.py` + handlers `on_question`
(catch-all free-text, no-flow) + `on_location`. Agronomist texts a question → field
resolved from «поле N» / «это поле» (last geo) → grounded in `field_card_text` (CropWise
ops/crop/NDVI/weather) + general knowledge → colloquial YandexGPT answer. Geolocation:
`db.field_at_point` (PostGIS ST_Contains) sets «это поле». Bot now answers ALL free text
as questions (chatbot behavior). Validated on поле 119. In field testing.

**Agro Q&A — refined 2026-06-17:** persona = concrete friendly colleague (specific brand
names + д.в. + norms, no «разрешённых в РФ»/«ознакомьтесь с Госкаталогом» boilerplate, active
voice); answers how-to-use-bot + how-to-photograph from a built-in guide; off-topic/unclear →
polite agronomist redirect (no hallucination). KEY: product recommendations are GROUNDED — for
«чем обработать <crop> от <target>» it extracts crop+target (YandexGPT) and pulls registered
products from `pesticide_applications` (Госкаталог, 14380 rows, db.get_registered_products),
LLM recommends ONLY from that list → fixed confidently-wrong advice (was suggesting Корсар, a
broadleaf herbicide, for grass weeds). agro_chat._registry_grounding gated by a recommendation-
question regex. Underlying LLM = in-RU YandexGPT (mediocre alone; grounding makes it correct).

**Agro Q&A — crop-safety hardening 2026-06-19 (Almas bug):** bot had recommended glyphosate/
dicamba(«ЛИНТУР»)/clopyralid for живокость in SUNFLOWER — all kill/damage the crop. Fixes
(`bot/agro_chat.py`): (1) broadened `_REC_RE` so «чем бороться с сорняком / уничтожить / сорняк /
вредитель» also triggers grounding (was missing → ungrounded hallucination); (2) `_extract`
now also returns `weed_class` (двудольн/злаков) — crop+specific-target often = 0 rows
(подсолнечник+живокость=0) so it falls back crop+target → crop+weed_class (подсолнечник+двудольн=30
real options) → crop-only only for generic questions; (3) when NOTHING is registered for
crop+object, grounding explicitly FORBIDS non-selective/other-crop products and tells the LLM to
be honest + suggest agro methods; (4) `_SYS` hard rule: never recommend a crop-damaging product;
(5) for подсолнечник/соя/рапс grounding appends a MANDATORY caveat that трибенурон-метил(Express)/
имазамокс(Clearfield) work only on tolerant hybrids. Verified: живокость/подсолнечник now returns
sunflower-registered products + hybrid caveat, no глифосат/дикамба.

**Structured photo diagnosis 2026-06-19 (`bot/diagnose.py`, commit b4657c3) — borrowed from
competitor «Андрей Тимофеевич»:** a photo CAPTIONED with a question («что это за сорняк и как
бороться?») routes (in on_photo/on_photo_document via `_DIAG_CAPTION_RE`) to `_handle_photo_diagnosis`
→ `diagnose()`: qwen vision IDs the object (diagnosis+confidence+symptoms+differential+phase) →
YandexGPT writes a TEMPLATED answer (🔬диагноз/📊уверенность/👁видно/❓дифференциал/🔎проверить/
🛡меры/⏱время) grounded via agro_chat `_registry_grounding`+`_literature_grounding` (named Госкаталог
products for the KNOWN crop + producer tags + CyberLeninka cites + crop-safety/hybrid caveats); low
confidence stays hedged. Crop resolved from caption or last field (`_diag_crop`) → we skip "какая
культура?" (our edge over the competitor, who must ask). A plain photo (no question caption) still
enters the labeling FSM. Verified on a real марь-белой photo: correct ID (Chenopodium album, 85%) +
sunflower-registered products. 2-model pipeline (qwen vision + YandexGPT), both in-RU; ~30–60s.

**Structured TEXT recommendation answers 2026-06-19 (commit dd06926):** the same structured format
now applies to text protection questions («чем обработать сою от осота?») via `agro_chat._REC_SYS`
(🌿 Объект / 🛡 Меры борьбы / 💊 Препараты [grounded, producer-tagged] / ⏱ Когда / 📚 Источники +
crop-safety caveat). Routed by GROUNDING PRESENCE in `answer()`: if `_registry_grounding` fired (real
crop+target question) → `_REC_SYS` (structured, 950 tok); else → conversational `_SYS` (bot how-to,
field-history, off-topic stay prose). Verified: soy/осот → structured w/ soy-registered products;
«как записать обработку» stays conversational.

**Producer tagging in recs 2026-06-19 (founder decision, LICENSING.md §2.4 v1.1):**
bot tags the MAJOR producer inline on each recommended препарат (e.g. «Корсар (Август)»),
sourced from the OFFICIAL Госкаталог `pesticide_applications.registrant` — NOT the copyrighted
atlases or the Avgust apk (server-backed React app, no bundled data; §2.2 atlas-content bans stay
in force). `db.producer_label(registrant)` maps → Syngenta/Bayer/BASF/Corteva/FMC/Adama/Август/
Щёлково Агрохим (verified: ВЗСП=Август's plant; «Дюпон Наука и Технологии»=DuPont RU→Corteva).
`agro_chat._registry_grounding` appends `[Producer]` to each line; `_SYS` tells the LLM to show it.
Full neutral list preserved (other/generic producers stay untagged ~1523 products); only origin is
flagged → legally clean + neutral. (Superseded the earlier separate-block design.) Verified soy:
«Алсион [Август]», «Артист [Bayer]».

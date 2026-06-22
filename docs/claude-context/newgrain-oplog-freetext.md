---
name: newgrain-oplog-freetext
description: "Free-text operation logging — routing fix, multi-field fan-out, and the local-fields vs CropWise-catalog gap"
metadata: 
  node_type: memory
  type: project
  originSessionId: f6ba0ea2-f3cc-48c0-898d-52d7a10271dd
---

**22 Jun 2026 bug batch (Almas/Evgenia) — all fixed & deployed:**
1. **Stuck field-prompt** (4052bcc): users trapped in OpLogForm.filling (field slot) had every
   later message — incl. a fresh field-less «подвоз/покос/грейдир» — read as a field number,
   looping «Не нашёл поле». Fix: in `_fill_slot`, if a reply `looks_like_oplog`, re-route it as a
   new op instead of forcing it into the slot. (General escape hatch; also added to the confirm-
   state text handler.)
2. **«номер/площадь» field refs** (e9d9701): agronomists write field as «<номер>/<площадь, га>»
   (124/92 = поле 124, 92 га). `find_fields_by_number` now normalises «124 / 92»→«124/92», tries
   the full value first (real slash-named fields like «Поле 121/140» still match), then falls back
   to the part before «/». 
3. **Implement (навесное/прицепное) capture** (773e241): CropWise machine_tasks have `implement_id`
   + an `/implements` catalog (Грейдер сд-105, Косилка КРН-2,1Б). `parse_op` now extracts
   `implement`; `build_machine_task` resolves it (`match_implement`, punctuation-insensitive) and
   flags `needs_implement` for покос/грейдир/культив/дисков/…; bot ASKS «какое оборудование?» when
   missing, sends `implement_id` on create. Transport (подвоз) doesn't ask.
4. **Multi-task batch** (ff6411c): several machine tasks in one message. `parse_operations` returns
   a LIST; >1 all-fieldless → `_handle_machine_batch` builds each, one «Создать все?», per-task
   ✅/⚠️. Field-spray batching still TODO.
5. **Assistant follow-ups** (f365709/c80ecd7): Telegram `on_question` had no history → bare follow-up
   «Предложите варианты» was deflected. Added a per-user Redis Q&A buffer (`flagleaf:chat:<tg>`, 4
   turns, 30-min) passed to `agro_answer`; `answer()` folds the last user question into the grounding
   query. Plus `_REC_RE` now matches падалиц/самосев and `_extract` maps падалица подсолнечника/рапса/
   сои → «двудольн», зерновых → «злаков» → so «падалица в сое» pulls real soy broadleaf herbicides.

**Bug (Евгения, 18 Jun 2026):** typed operations were "accepted" by the bot but never
reached CropWise. Two causes, both fixed & deployed (commit 58afab0):

1. **Confirmation theater.** Free-text operations only entered the log flow via `/log`
   or a button. Typed text (which the bot guide tells users to send) fell through to the
   conversational assistant (`on_question`/agro_chat), which only *described* logging and
   generated a fake «запись принята» — nothing parsed or saved. Fix: `bot/oplog_match.py`
   `looks_like_oplog(text)` (stdlib-only, unit-tested) classifies statement-vs-question;
   `on_oplog_freetext` (StateFilter(None), registered BEFORE the Q&A catch-all) routes
   statements into the real parse→confirm(✓)→save+CropWise flow. Questions still go to Q&A.

2. **Single-field parser.** `bot/parse_op.py` returned one `field`, so «опрыскал поля 262,
   252, 251 …» parsed to None. Now returns a `fields` LIST; the log flow resolves each
   (`_set_fields`), shows one confirm card, and on save FANS OUT to one field_treatments
   row + one CropWise push per field (dup-safe via the 0018 natural key + [[newgrain-architecture-audit]]
   sync flag). Also feed the parser today's date so «17 июня» → current year (was 2024).

**Report-paste dedup (19 Jun 2026, commit 4443a4a).** Евгения reported the самоходка
report «didn't work» — actually it DID create ops, but those «1-я обработка подсолнечника»
operations were ALREADY in CropWise (created natively 14 May), so the bot made duplicates,
and a re-paste showed «создано 0/6 · код 422» (CropWise 422s a duplicate idempotency key),
which looked like a hard failure. Fixes: `create_ops` now dedups on the operation IDENTITY
(field_id + work_type_id + season) across ALL CropWise ops — so an op that already exists
(native OR ours) reports «уже создано ранее» instead of duplicating; idempotency key is now
date-less (was date-stamped → re-paste next day duplicated). `on_report_create` reports
created / уже было ранее / не удалось separately + shows the real error detail. NOTE:
(field,wt,season) isn't globally unique in CropWise (1309 legit historical repeats, mostly
generic work types/old seasons) — acceptable for pass-numbered work types; watch for
over-blocking a legit 2nd pass of a generic work type. Bot dup ops 20616–20620 (18 Jun)
duplicate native May-14 ops — founder said LEAVE THEM (do not delete); the dedup fix prevents
new dups going forward.

**Driver namesake disambiguation (19 Jun 2026).** Machine-task / report driver matching
(`cropwise_report.driver_matches`/`match_driver`) resolves «Фамилия [Имя] [Отчество]» in
layers: surname → candidates; имя then отчество narrow (initials work, «…С»); ties prefer
ACTIVE records (CropWise has many stale `no_access` namesake duplicates — that was the real
cause of apparent collisions). Parsers (`parse_op`, report `_SYS`) keep имя+отчество. For
TRUE active full-namesakes the typed text can't separate (CropWise has NO human-typeable
unique id — rfid/СНИЛС/ИНН empty, email=creator's, phone on ~1/3), the КамАЗ machine-task
flow ASKS: `build_machine_task` sets `driver_options`, `_handle_machine_task` shows buttons,
`on_mt_driver_pick` applies the choice. Founder should also dedup duplicate driver records
in CropWise (root cause). Report-paste flow auto-picks the first best (no per-row prompt).

**Field-resolution architecture (important):** conversational `/log` resolves fields against
the LOCAL `fields` table (`find_fields_by_number`/`resolve_field`), which holds ~286 of
CropWise's 443 fields under **farm_id=1** (Евгения id7 is farm 1). The report-paste flow
(`catalog/cropwise_report`) resolves against the CropWise CATALOG (all 443). So a field that
exists in CropWise but wasn't in the partial `ingest_fields` xlsx import won't resolve in
`/log`. Follow-up worth doing: refresh local `fields` from a full CropWise export/API so
`/log` covers every field. Common ones (262/252/251/119 · Хлевище) DO resolve.

**КамАЗ logistics — BUILT (18 Jun 2026, commit ef7e629).** Founder clarified: in «...
двулучанский на камазе 286 ... подвоз воды», Двулучанский is the DRIVER (not a field/
отделение), and water-hauling has NO single field (one trip serves many). So it's a CropWise
**machine_task** (driver+machine+work_type+date, no field), NOT an agro_operation. Flow:
parse_op now also returns `driver`+`machine`; `oplog_match.is_logistics_op` (подвоз/перевоз/
доставка) routes to `_handle_machine_task` → `cropwise_report.build_machine_task` resolves
work_type (ALL types)/machine/driver → confirm card → `create_machine_task` POSTs
/machine_tasks (status done, season=year, start/end times, auto_created=false, external_id
`flagleaf-mt-…` for idempotency). Verified up to the write: «подвоз воды»→wt 127, «КамАЗ 286»
→Камаз М286АН31 (id14), Двулучанский→id 334618. **The POST itself is unverified (Claude is
blocked from CropWise writes) — Евгения validates the first real one.**
⚠️ **Duplication caveat to confirm with Евгения:** machine_tasks are normally GPS-AUTO-created
from the truck's tracker (all sampled had auto_created=true). If КамАЗ 286 has a tracker, the
task already appears in CropWise automatically — manually entering via the bot would DOUBLE it.
Confirm whether these trucks have GPS before relying on manual entry.

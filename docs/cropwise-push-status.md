# Bot → CropWise push — LIVE (in field testing)

*As of 2026-06-17.*

An agronomist reports an операция to the bot (voice/NL via `/log` or the daily
nudge) → it's created in CropWise automatically as a **completed** operation, no
double entry. Reverse of the read sync. **Wired into the bot and confirmed
end-to-end** (op 20521: status=done + внесение Корсар fact_rate 1.8).

## How it works
`catalog/cropwise_push.py` maps a parsed op to CropWise's dictionaries (field by
name/number+area, work-type by category/keyword, product → chemical/fertilizer/seed
id, unit from the product's base unit) and creates it in **three steps** — because
the operation and the внесение are **separate CropWise resources** (per support, a
single request can't do both):

1. `POST /agro_operations` — create the operation (planned).
2. `POST /application_mix_items` — add the внесение (with `agro_operation_id`,
   `fact_rate`/`fact_amount`, unit, rate_basis). This is the actual application.
3. `PUT /agro_operations/{id}` — set `status=done`.

Wired in `handlers.on_oplog_save`: after the local `field_treatments` save
(`source='bot'`), `push_treatment()` runs off the event loop. A CropWise failure is
only a warning — the local history row is never blocked. The CropWise catalog is
cached ~1h in the bot. Dedup: the weekly pull (`cropwise_ops_sync`) skips ops whose
`idempotency_key` starts with `flagleaf-` (our own pushes, already stored locally).

## Gotchas solved (so we don't relearn them)
- **`strict_ami_done_status` was a CropWise SETTING**, not an API limit —
  «запрет на закрытие агрооперации без внесений». The owner unticked it. With it on,
  no API call can close an operation without an внесение.
- **`completed_datetime` must be ≤ now** — CropWise rejects a future time; we use
  `now − 15 min` for today (midday for past dates).
- **Embedded `application_mix_items` in the operation POST are dropped** — the
  внесение must be its own `POST /application_mix_items` with `agro_operation_id`.
- Token has full write access (create→201, delete→204). No separate "внесение"
  endpoint name — it's `/application_mix_items`.

## Decisions
- **Confirm-before-push**: the `/log` ✓ confirmation *is* the confirm; on ✓ it pushes.
- **Unmatched product**: still create the operation, flag «впишите внесение вручную».

## Slot-filling & gap-asking (handlers, OpLogForm.filling)
If a logged op is missing a required slot, the bot asks for it one at a time
(text or voice) until complete, instead of dead-ending or saving a partial op:
- **field** — always; resolves across ALL 283 fields, not just pilots. If a number
  repeats in several отделения it asks «какое отделение?» and resolves from the answer.
- **product** — for protection/fertilizer/sowing ops.
- **dose** — once a product is known (needed for the внесение rate).
- **crop** — only if the field has none on record.
Harvest/tillage (no substance) only need the field.

## Validation (2026-06-17, `catalog/oplog_audit.py` + `oplog_parse_test.py`)
Against the full CropWise history: **100%** product recognition (357/357), **100%**
work-type mapping (167/167), all real fields resolve, clarification fires only on
genuinely incomplete ops (~6.5%). Parser spot-check on realistic phrasings: **29/30**
clean extraction (the 1 miss is gracefully handled — bot asks for the field);
**4/4** correct dose-clarification. Re-run both tools as new ops/products arrive.

## Status: IN FIELD TESTING (from 2026-06-17)
Live; awaiting real use by the agronomists and the CropWise operator (who normally
records ops manually) to surface bugs before we consider it done.

## CLI (for testing / cleanup)
```
python -m catalog.cropwise_push --note "опрыскал поле 119 Корсаром 1.5 л/га сегодня"        # dry preview
python -m catalog.cropwise_push --note "…" --post     # real create (3-step)
python -m catalog.cropwise_push --delete <id>          # remove a test op
```

## Possible follow-ups
- Map more work-types / units as real ops reveal gaps.
- Surface the created CropWise operation id back to the agronomist (currently just
  «отправлено в CropWise»).

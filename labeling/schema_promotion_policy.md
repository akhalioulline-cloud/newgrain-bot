# Schema-promotion policy

**Version:** 1.0 · 29 May 2026
**Scope:** how new weed species (and, later, new disease/stress classes) enter the Flagleaf schema — the data-driven alternative to bulk-importing an atlas TOC.

---

## The rules in one paragraph

A species moves through three **independent tiers**, each with its own
threshold. Tier promotion is always upward, always on evidence, never
based on the atlas TOC alone.

- **Tier 1 — in the bot's species dictionary** (`weed_species`).
  Threshold: **≥1 sighting** in submissions OR a clear CAO/spec reason
  to expect it. Effect: agronomist can pick the species via /Другой
  autocomplete; comments referencing it become queryable. Cost: free
  (one migration INSERT row).

- **Tier 2 — in the CVAT label list** (`labeling/cvat_labels.json` →
  CVAT project label set). Threshold: **≥1 actual sighting** at our
  fields (not pre-emptive). Effect: annotator can draw a properly-typed
  bbox for it; labeled bboxes accumulate in our `labels` table from the
  first occurrence; the existing CVAT task picks up new labels
  automatically. Cost: 1 line in JSON + 1 click to re-import to CVAT.

- **Tier 3 — in the CV training class set**. Threshold: **≥30 labeled
  examples** of that species from our own fields. Why this number: at
  <30 images a YOLO-style detector can't generalize a class reliably,
  and per-class data sparsity *degrades all other classes* in the same
  training run. Cost: real — every weak class hurts the trained model.
  This is the gate that actually matters.

The key distinction this codifies: **adding a class to CVAT is cheap
and lossless** (structured data starts accumulating); **adding a class
to training is expensive** (degrades model accuracy on every class
until it has enough data of its own). They're not the same decision.

| Tier | Lives in | Threshold | What it enables |
|---|---|---|---|
| 1 | `weed_species` | ≥1 sighting OR known-relevant | Bot UX: pickable name, free-text matching |
| 2 | `cvat_labels.json` + CVAT project | ≥1 sighting | Annotator: structured bbox label; `labels` table accumulates |
| 3 | CV training schema | ≥30 labeled examples | Model: actually targets this class |

---

## Monthly review query

Run this on the first Monday of each month (cron-eligible later; manual
for now). Two outputs that drive promotion decisions:

**(a) Most-typed free-text species — promote candidates for the dictionary:**

```sql
SELECT
  s.subcategory AS typed,
  count(*) AS n_photos
FROM submissions s
LEFT JOIN weed_species ws ON ws.latin_name = s.subcategory
WHERE s.subcategory IS NOT NULL
  AND ws.id IS NULL                 -- not matched to dictionary
  AND s.status <> 'draft'
  AND s.created_at >= NOW() - INTERVAL '90 days'
GROUP BY s.subcategory
HAVING count(*) >= 3                -- ignore one-offs
ORDER BY n_photos DESC;
```

For each row: decide latin name (cross-check with the Syngenta atlas TOC
*for taxonomic reference only* — see `../LICENSING.md`), add to
`weed_species` via the next migration.

**(b) Dictionary species crossing the CV-training threshold:**

```sql
SELECT
  ws.latin_name,
  ws.russian_name,
  count(*) AS n_photos,
  ws.is_regional_top
FROM submissions s
JOIN weed_species ws ON ws.latin_name = s.subcategory
WHERE s.status IN ('ready_for_labeling', 'in_labeling', 'labeled', 'in_dataset')
GROUP BY ws.id
ORDER BY n_photos DESC;
```

For any species crossing 30 photos and not yet in `labeling/cvat_labels.json`:
add to the CVAT label spec, re-import to the CVAT project, mark the
species in this doc's tracking table below.

Also: any species crossing ~20 photos and not yet `is_regional_top`:
promote to the inline keyboard (one-line UPDATE in a migration).

---

## Promotion tracking (append as it happens)

| Date | Species | Latin | From → To | Note |
|---|---|---|---|---|
| 29 May 2026 | Чина клубненосная | *Lathyrus tuberosus* | unknown → tier 1 (dict) | First seen via Almas's free-text comment; added in migration 0005. |
| 29 May 2026 | Мокрица (Звездчатка средняя) | *Stellaria media* | unknown → tier 1 (dict) | Added pre-emptively per `class_gaps_from_atlases.md` recommendation. |
| 29 May 2026 | Пастушья сумка | *Capsella bursa-pastoris* | unknown → tier 1 (dict) | Same. |
| 29 May 2026 | Метлица обыкновенная | *Apera spica-venti* | unknown → tier 1 (dict) | Same — major wheat weed in CBE, atlas item. |
| 29 May 2026 | Чина клубненосная | *Lathyrus tuberosus* | tier 1 → tier 2 (CVAT) | Observed 1× by Almas; promoted to tier 2 same day. NOT in CV training class set — awaiting ≥30 examples. |
| 10 Jun 2026 | Молочай прутьевидный | *Euphorbia virgata* | unknown → tier 2 (`euphorbia`) | Observed; migration 0008. |
| 10 Jun 2026 | Одуванчик | *Taraxacum officinale* | unknown → tier 2 (`taraxacum`) | Observed; migration 0008. |
| 10 Jun 2026 | Полынь | *Artemisia vulgaris* | unknown → tier 2 (`artemisia`) | Observed; migration 0008. Genus-level; CAO to confirm exact species. |
| 10 Jun 2026 | Хвощ полевой | *Equisetum arvense* | unknown → tier 2 (`equisetum`) | Observed; migration 0008. |
| 10 Jun 2026 | Спорыш / горец птичий | *Polygonum aviculare* | unknown → tier 2 (`polygonum_aviculare`) | Observed; migration 0008. Distinct from existing `polygonum` (P. convolvulus). |
| 10 Jun 2026 | Бодяк полевой | *Cirsium arvense* | alias added | Same species as Осот полевой; alias only, no new class. |
| 10 Jun 2026 | Молокан / молочай | *Euphorbia virgata* | resolved → `euphorbia` | CAO (Almas) confirmed he meant молочай, not молокан (Lactuca). Submission 50561ec9 hint corrected to "Молочай прутьевидный". NOT adding "молокан" as a Euphorbia alias — it botanically means Lactuca tatarica; a global alias would mis-tag a real Lactuca sighting later. |

---

## What this is NOT

- **Not a blocker for collection.** Agronomists keep typing whatever they
  see via /Другой. The free-text field accepts anything; promotion
  decisions never gate field work.
- **Not a CVAT label-spec rewrite each time.** Add to the dictionary
  cheaply (one INSERT row); add to CVAT only when CV training is
  actually about to use the class.
- **Not a substitute for the agronomist's judgment.** If the CAO says
  *"this one matters, add it now"* — add it now. The 30-image rule is
  the default, not a veto.

---

## Why we don't bulk-import an atlas TOC

Three reasons (consolidated from the Tier-3 reasoning):

1. **CV training needs ≥30 images per class.** Empty schema classes don't
   help the model and hurt the UI.
2. **Inline keyboard caps at ~8 visible buttons on a phone.** Adding 60
   species makes selection *worse*, not better. The /Другой path scales
   freely; the keyboard does not.
3. **An atlas is a *catalog of possible weeds*, not a forecast of what's
   at Alekseyevka.** Most atlas-listed species won't show up in our
   pilot fields in meaningful frequency. The right signal is what the
   agronomist actually photographs.

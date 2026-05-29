# Schema-promotion policy

**Version:** 1.0 · 29 May 2026
**Scope:** how new weed species (and, later, new disease/stress classes) enter the Flagleaf schema — the data-driven alternative to bulk-importing an atlas TOC.

---

## The rule, in one sentence

A new species is promoted to a CV training class only when **≥30 labeled
images of that species accumulate from our own fields**, reviewed monthly.

Why this number: at <30 images, a YOLO-style detector cannot generalize a
class reliably (the per-class minimum mentioned across the Ultralytics
docs and most published CV-in-agriculture work). Below the threshold, a
"class" in the schema is taxonomic clutter that hurts UX without helping
the model.

---

## The three states a species can be in

| State | What it means | How it's reached |
|---|---|---|
| **Unknown to the system** | Not in `weed_species`; agronomist types it via /Другой; lands in `submissions.subcategory` as free text. | Default for everything not yet seen. |
| **In the dictionary, not regional-top** | Row in `weed_species` with `is_regional_top = false`. Not shown in the inline keyboard; can still be referenced by free-text matching or future autocomplete. | Add via migration (small) once observed at all. |
| **Regional top** | `is_regional_top = true`. Shown as one of the ~8 buttons on the inline species keyboard. | Promote via migration after the species shows up regularly in submissions. |
| **CV training class** | Has a code in `labeling/cvat_labels.json` and is one of the targets the v0/v1/v2/v3 detectors are trained on. | Promote only when ≥30 labeled images of it exist from our fields. |

A species can sit at any state; movement is **always upward**, on evidence.

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
| 29 May 2026 | Чина клубненосная | *Lathyrus tuberosus* | unknown → dictionary | First seen via Almas's free-text comment; added in migration 0005. |
| 29 May 2026 | Мокрица (Звездчатка средняя) | *Stellaria media* | unknown → dictionary | Added pre-emptively per `class_gaps_from_atlases.md` recommendation. |
| 29 May 2026 | Пастушья сумка | *Capsella bursa-pastoris* | unknown → dictionary | Same. |
| 29 May 2026 | Метлица обыкновенная | *Apera spica-venti* | unknown → dictionary | Same — major wheat weed in CBE, atlas item. |

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

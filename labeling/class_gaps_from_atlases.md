# Class-schema gap analysis from Syngenta atlases (TOC only)

**Method:** read only the table of contents of four Syngenta-published atlases
(weeds 2023, soybean diseases NEW, sunflower diseases 2023, cereal pests 2023),
compare against the current Flagleaf class taxonomy in `tech_spec` §2.3.
**No atlas content (text, photos, recommendations) is used or redistributed.**
The TOC is treated as a free signal about which classes a working Russian
agronomist deems worth identifying — it informs the question to ask the CAO,
not the answer. See `LICENSING.md` for the full policy.

---

## 1. WEEDS — current 15 classes vs atlas TOC (~60 species)

All 5 of our **P0 weed classes** are confirmed in the atlas (ambrosia, cirsium,
convolvulus, chenopodium, amaranthus) — taxonomy is well-anchored. So is
`helianthus_v`, indirectly (the atlas treats volunteer crops as field weeds in
its agronomic framing).

Atlas TOC species **not** in our 15 that are strong CBE candidates to discuss
with the CAO:

| Latin / Russian | Why a candidate |
|---|---|
| *Stellaria media* — звездчатка средняя (мокрица) | Extremely common in cereals across CBE; trivial visual ID for the annotator. |
| *Capsella bursa-pastoris* — пастушья сумка | Ubiquitous early-season; distinctive triangular silicles. |
| *Apera spica-venti* — метлица обыкновенная | Major wheat weed in CBE; competes hard in winter wheat. |
| *Alopecurus myosuroides* — лисохвост мышехвостовидный | **Notorious for herbicide resistance** — directly relevant to the Y2 Resistance Map module. |
| *Veronica spp.* — вероника персидская / плющелистная | Common early-season broadleaf in winter cereals. |
| *Sinapis arvensis / Brassica spp.* — горчица полевая, редька дикая | Cruciferous weeds in OSR/soy; visually overlap with rapeseed volunteer. |
| *Equisetum arvense* — хвощ полевой | Hard-to-control rhizomatous; high economic impact when present. |

**Recommendation:** at the CAO kickoff conversation, walk this short list and
ask: *"которые из этих видов вы считаете приоритетными на наших трёх полях
в сезон 2026?"* If he confirms 2–3, add them to the schema before
labeling starts — much cheaper than expanding mid-season.

---

## 2. SOYBEAN DISEASES — current spec has **ZERO** soy disease classes

This is the biggest gap. Soybean is one of the three anchor crops at
Alekseyevka (Поле 121/140, 140 ha). The current `tech_spec` §2.3 disease
taxonomy is wheat- and sunflower-only.

The soy disease atlas TOC lists 16 fungal + bacterial entries. The
economically dominant ones for our region:

| Class to add | Latin | Why |
|---|---|---|
| `soy_sclerotinia` | *Sclerotinia sclerotiorum* (Белая гниль) | Major yield-killer on soy in CBE; visually distinctive (white cottony mycelium + sclerotia). |
| `soy_peronospora` | *Peronospora manshurica* (Ложная мучнистая роса) | Common, high-economic; visual signature (chlorotic upper-leaf patches + downy sporulation underleaf). |
| `soy_septoria` | *Septoria glycines* (Септориоз сои) | Very common; high CV-learnability (brown spots, defined margins). |
| `soy_cercospora_frogeye` | *Cercospora sojina* (Церкоспороз округлая серая) | Growing problem; "frogeye" spots are distinctive. |
| `soy_fusarium_root` | *Fusarium* spp. (Фузариозная корневая гниль) | Below-ground; lower CV priority but high agronomic signal. |

Plus three more the atlas covers that may be P2-tier for Г1: антракноз
(*Colletotrichum truncatum*), фомопсис (*Phomopsis longicolla*),
пепельная гниль (*Macrophomina phaseolina*).

**Recommendation:** add at least the first 3 (`soy_sclerotinia`,
`soy_peronospora`, `soy_septoria`) to the disease schema. Without any soy
disease classes, the Поле 121/140 site contributes nothing to the disease
training corpus.

---

## 3. SUNFLOWER DISEASES — current 3 classes are reasonable but incomplete

Current spec: `sunflower_phomopsis`, `sunflower_phoma`, `sunflower_alternaria`.
Atlas TOC covers 12 disease entries. Three are confirmed already in our
schema; the rest are real gaps:

| Class to add | Latin | Why |
|---|---|---|
| `sunflower_sclerotinia` | *Sclerotinia sclerotiorum* (Белая гниль) | One of the two most damaging sunflower diseases in Russia; very visible at flowering/late stages. |
| `sunflower_downy_mildew` | *Plasmopara halstedii* (Ложная мучнистая роса) | High impact, P0-tier per ВНИИМК; distinctive seedling symptoms. |
| `sunflower_verticillium` | *Verticillium dahliae* (Вертициллёзное увядание) | Soil-borne wilt; symptoms visible mid-season. |
| `sunflower_rust` | *Puccinia helianthi* (Ржавчина) | Distinctive orange pustules; high CV-learnability. |
| `sunflower_botrytis` | *Botrytis cinerea* (Серая гниль) | Common late-season head rot. |

**Recommendation:** add at least `sunflower_sclerotinia` and
`sunflower_downy_mildew` (the two highest-impact). Five classes is still
manageable; ten starts crowding the bbox budget.

---

## 4. CEREAL PESTS — current spec has **ZERO** pest classes; recommend keep that for Г1

The cereal-pest atlas covers ~30 species (flea beetles, Hessian fly, ground
beetles, sawflies, Sunn pest, aphids, leafhoppers, click beetles, etc.).

The most economically important for wheat in CBE:

- *Eurygaster integriceps* — клоп вредная черепашка (Sunn pest). The single
  most damaging wheat pest in Russia south of Moscow.
- *Schizaphis graminum / Sitobion avenae* — злаковые тли. Aphids + BYDV vector.
- *Oulema melanopus* — пьявица красногрудая (cereal leaf beetle).
- *Cephus pygmaeus* — хлебный пилильщик (wheat stem sawfly).

**Recommendation: do NOT add pests to Г1.** Three reasons:
1. The current 15-weed + 10-disease taxonomy is already ambitious for the
   90-day window. Scope creep is in our risk register (R3).
2. Insect CV is materially harder than plant CV: smaller targets, motion,
   higher lighting sensitivity, often inside the canopy.
3. The Г1 kill criterion is "≥75% mAP on 5+ key weed species" — pest classes
   wouldn't move that needle.

Instead: **note pests as a Y2 schema candidate** in the `tech_spec`. Flag
*Eurygaster integriceps* and *злаковые тли* explicitly so the Y2 planning
can start with them.

---

## 5. Net recommended schema update (before labeling kicks off)

| Bucket | Spec v1.1 has | Suggested for Г1 final |
|---|---|---|
| Weeds | 15 classes | 15 + 2–3 from atlas TOC after CAO confirms (likely `stellaria_media`, `apera_spica_venti`, possibly `alopecurus_myosuroides` for the resistance-map angle) |
| Diseases | 10 (7 wheat + 3 sunflower) | +3 soy (`soy_sclerotinia`, `soy_peronospora`, `soy_septoria`) and +2 sunflower (`sunflower_sclerotinia`, `sunflower_downy_mildew`) → 15 total |
| Stresses | 6 | unchanged (atlases don't change this) |
| Pests | 0 | unchanged for Г1; flag Sunn pest + cereal aphids as Y2 priority |

If the CAO confirms 2 weeds and we adopt the 5 disease additions, total
goes from **31 → 38 classes**. Still well within the labeling-budget envelope
(annotator handbook §2.6 calls 50 photos/day target; class count doesn't
linearly affect throughput).

---

## 6. What to do operationally

1. **Bring this memo to the kickoff CAO conversation** as a one-pager
   discussion guide. Don't show the atlas to the CAO (avoid framing it as
   "Syngenta says…"); show this list as our own taxonomy proposal.
2. After his sign-off, update `labeling/cvat_labels.json` to add the
   confirmed classes (one-line PR — codes for new species).
3. Mirror the additions into `tech_spec` §2.3 in the next adjustment pass
   (a v1.2 callout, not a full rewrite).
4. Re-import the updated label spec into the CVAT Cloud project
   `weeds-diseases-stress`.

The atlas itself stays out of every downstream artifact — see `LICENSING.md`.

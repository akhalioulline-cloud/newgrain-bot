# Public datasets — license audit & approval log

**Version:** 1.0 · 29 May 2026
**Authority:** [LICENSING.md](../LICENSING.md) — base policy.
**Scope:** every public dataset evaluated for inclusion in the Flagleaf
bootstrap (v0) CV training corpus, with explicit license verdict per dataset.

Each row's verdict is binding. **Do not download or use a dataset whose row
says ❌ EXCLUDED.** When you add a new candidate dataset, append a row to
this file *before* downloading.

---

## Verdicts at a glance

| # | Dataset | Status | License | Why |
|---|---|---|---|---|
| 1 | North Dakota Weed Dataset | ✅ APPROVED | CC BY 4.0 | Standard commercial-OK. |
| 2 | 4Weed Dataset (Purdue) | ✅ APPROVED | CC0 (public domain) | Best possible license. |
| 3 | Multi-modal Weed Dataset (wheat, China) | ✅ APPROVED | CC BY | Frontiers open access. |
| 4 | GrowingSoy / soy-segmentation-ds | ✅ APPROVED | MIT | Repo + dataset MIT. |
| 5 | Sunflower Fruits & Leaves (Mendeley) | ✅ APPROVED | CC BY | For sunflower diseases. |
| 6 | **MFWD** (Moving Fields Weed Dataset) | ⏳ PENDING | code MIT; **data license TBD** | Must read Nature article "Data Availability" before download. |
| 7 | **OPPD** (Open Plant Phenotype Database) | ❌ **EXCLUDED** | **CC BY-NC-SA 4.0** | Non-commercial — incompatible with Flagleaf. |
| 8 | PlantVillage soybean subset | ⏸️ PARKED | license inconsistent across mirrors; soy coverage thin | Re-evaluate only if other soy sources insufficient. |
| 9 | Roboflow Universe weed/disease subsets | ⏸️ PARKED | mixed (per-subset) | Per-subset audit required; defer until specific need. |

---

## 1. North Dakota Weed Image Dataset ✅

- **Authoritative source:** *Multi-format open-source weed image dataset for real-time weed identification in precision agriculture*, ScienceDirect / PMC ([PMC10618417](https://pmc.ncbi.nlm.nih.gov/articles/PMC10618417/), 2023)
- **License:** **CC BY 4.0** — confirmed via paper and dataset metadata
- **Content:** 3,975 images, **5 species**: kochia (*Bassia scoparia*), common ragweed (*Ambrosia artemisiifolia* — **our `ambrosia`, P0**), horseweed (*Erigeron canadensis*), redroot pigweed (*Amaranthus retroflexus* — **our `amaranthus`, P0**), waterhemp (*Amaranthus tuberculatus*)
- **Capture modality:** handheld camera **and unmanned aerial system (UAS)** — direct fit for Flagleaf's planned drone capture
- **Formats:** multi-format (paper title); includes YOLO-compatible annotations
- **Coverage of our schema:** 2/15 P0 weeds directly; horseweed, kochia, waterhemp not in our taxonomy but harmless to include
- **Attribution required in:** `data-card` of any model trained on it, and any external publication

## 2. 4Weed Dataset ✅

- **Authoritative source:** *4Weed Dataset: Annotated Imagery Weeds Dataset*, Aggarwal et al., arXiv:2204.00080
- **Location:** [osf.io/w9v3j](https://osf.io/w9v3j/)
- **License:** **CC0 (public domain)** — no attribution required; best possible terms
- **Content:** 618 RGB images, **4 species**: cocklebur (*Xanthium strumarium* — **our `xanthium`, P2**), foxtail (*Setaria viridis* — **our `setaria`, P1**), redroot pigweed (*Amaranthus retroflexus* — **our `amaranthus`, P0**), giant ragweed (*Ambrosia trifida*, sister species to *A. artemisiifolia* — useful proxy for **our `ambrosia`, P0**)
- **Capture:** field + Purdue greenhouse, handheld
- **Coverage of our schema:** 3/15 directly + 1 useful sister-species
- **Small dataset** — useful as auxiliary, not primary

## 3. Multi-modal Weed Dataset (wheat) ✅

- **Authoritative source:** Xu et al. 2022, *Frontiers in Plant Science*, [10.3389/fpls.2022.936748](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2022.936748/full)
- **License:** **CC BY** (Frontiers open access)
- **Content:** 1,288 paired (RGB + depth + 3-channel encoded) images, 21,227 bbox annotations, multi-view (9 angles per scene). Wheat at tillering & jointing stages.
- **Coverage of our schema:** wheat crop context (matches Поле 76/108 at Alekseyevka). Specific weed species not listed in the search-result abstract — verify on download whether *Avena fatua* or other Russian wheat weeds are covered.
- **Modality note:** depth channel won't be used by our v0 (single-camera phone capture); use RGB only.

## 4. GrowingSoy / soy-segmentation-ds ✅

- **Authoritative source:** Steinmetz et al. 2024, [arXiv:2406.00313](https://arxiv.org/abs/2406.00313), repo: [github.com/raulsteinmetz/soy-segmentation-ds](https://github.com/raulsteinmetz/soy-segmentation-ds)
- **License:** **MIT** (per the GitHub repo)
- **Content:** 1,000 human-annotated + augmented images. **Instance segmentation, COCO format** (made via Roboflow). 3 classes: *Glycine max* (soy crop), *Amaranthus viridis* (caruru — sister species to our `amaranthus`), *Cynodon dactylon* (Bermudagrass)
- **Coverage:** soy crop context — direct fit for Поле 121/140 (Соя). Useful for the v0 model's ability to *not* mis-classify soy seedlings as weeds (negative-example training).
- **Stage coverage:** seedling → harvest — full season

## 5. Sunflower Fruits & Leaves Dataset (Mendeley) ✅

- **Authoritative source:** [PMC8980537](https://pmc.ncbi.nlm.nih.gov/articles/PMC8980537/), 2022 *An extensive sunflower dataset…*
- **Location:** Mendeley Data, [doi.org/10.17632/b83hmrzth8.2](https://doi.org/10.17632/b83hmrzth8.2)
- **License:** **CC BY** (per article's open-access notice)
- **Content:** 467 original + 1,668 augmented images (2,135 total). **4 classes:** Gray Mold (*Botrytis cinerea* — matches **our `sunflower_botrytis` gap-list class**), Downy Mildew (*Plasmopara halstedii* — matches **our `sunflower_downy_mildew` P0 gap-list class**), Leaf Scars, healthy leaves.
- **Coverage of our schema:** 2 of the 5 sunflower-disease classes proposed in [labeling/class_gaps_from_atlases.md](../labeling/class_gaps_from_atlases.md). Strong signal for `sunflower_downy_mildew`.
- **Note:** images are *leaves close-up*, not in-canopy whole-plant. Domain shift to phone-photo in-field will be significant; expect bootstrap-only utility.

## 6. MFWD (Moving Fields Weed Dataset) ⏳ PENDING

- **Authoritative source:** Genze et al. 2024, *Scientific Data* [10.1038/s41597-024-02945-6](https://www.nature.com/articles/s41597-024-02945-6); repo [github.com/grimmlab/MFWD](https://github.com/grimmlab/MFWD)
- **License status:** **code = MIT (confirmed). Dataset license = TBD.** Nature Scientific Data typically requires CC-BY-style data terms but it must be verified in the article's "Data Availability" section before download.
- **Content:** 94,321 images covering **28 weed species** in maize and sorghum, Germany. Bbox + instance segmentation + multiple-object-tracking annotations. Format compatible with CVAT.
- **Expected coverage of our schema:** if approved, this is the **single most valuable bootstrap source** — likely covers `ambrosia`, `amaranthus`, `chenopodium`, plus possibly `galium`, `polygonum`, `avena`, and others. Compensates for the OPPD exclusion.
- **Download method:** custom FTP script `download_by_ftp.py` from the repo — supports per-species download (e.g. `python3 download_by_ftp.py species 'AMARE, CHEAL, AMBEL'` for amaranthus / chenopodium / ambrosia using EPPO codes).
- **Action item before approval:** open the Nature article, read the "Data Availability" section, record the data license in this file. If non-commercial — exclude.

## 7. OPPD (Open Plant Phenotype Database) ❌ EXCLUDED

- **Source:** Madsen et al. 2020, *Remote Sensing*; site [vision.eng.au.dk/open-plant-phenotyping-database](https://vision.eng.au.dk/open-plant-phenotyping-database/)
- **License:** **CC BY-NC-SA 4.0** — confirmed directly on the official Aarhus University page: *"This work is licensed under a Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International – Licens."*
- **Why excluded:** the **NC (non-commercial)** clause is incompatible with Flagleaf as a commercial product per [LICENSING.md §4](../LICENSING.md). The SA (share-alike) clause would further force us to release derivative models under the same NC license, which is doubly disqualifying.
- **What we lose:** 7,590 images, 47 species with EPPO codes, including likely coverage of `chenopodium`, `galium`, `polygonum` — three classes in our schema this dataset uniquely covered well among the spec's six candidates.
- **Mitigation:** if MFWD's data license clears (item 6), MFWD likely covers the same three species. If MFWD is also non-commercial — `chenopodium`, `galium`, `polygonum` become **ground-up labeling priorities** at Alekseyevka.

## 8. PlantVillage soybean subset ⏸️ PARKED

- **Source:** the well-known PlantVillage corpus exists in many forks (Kaggle, GitHub `spMohanty/PlantVillage-Dataset`, IEEE DataPort)
- **Status:** license is inconsistent across mirrors; original Penn State terms call it "open-source research and educational" — that wording is precisely the ambiguity LICENSING.md warns about for commercial use. Plus, the soybean subset within PlantVillage is thin and doesn't cover our priority soy diseases (sclerotinia / peronospora / septoria glycines) at depth.
- **Verdict:** **do not download** until/unless the soy disease classes turn out to be impossible to label from our own fields and PlantVillage's specific subset can be license-cleared with original Penn State authors.

## 9. Roboflow Universe ⏸️ PARKED

- **Status:** thousands of community-uploaded subsets, **licenses vary per upload** (some CC-BY, some unstated, some explicitly NC). The spec explicitly calls them out as "проверять каждый."
- **Verdict:** no blanket approval. Add a row here for each specific subset before downloading.

---

## Net coverage assessment

**Approved sources cover (with high confidence):**

| Our class | Priority | Confirmed bootstrap coverage |
|---|---|---|
| `ambrosia` | P0 | North Dakota ✓, 4Weed (A. trifida proxy) ✓ |
| `amaranthus` | P0 | North Dakota ✓, 4Weed ✓, GrowingSoy (A. viridis proxy) ✓ |
| `setaria` | P1 | 4Weed ✓ |
| `xanthium` | P2 | 4Weed ✓ |
| `sunflower_downy_mildew` | P0 (gap-list addition) | Mendeley sunflower ✓ |
| `sunflower_botrytis` | gap-list addition | Mendeley sunflower ✓ |

**5 weed classes + 2 disease classes** with confirmed CC-BY-or-better public coverage.

**Conditional bootstrap (depends on MFWD verdict):**
- `chenopodium` (P0), `galium` (P2), `polygonum` (P2), possibly `avena` (P1), `echinochloa` (P1)
- If MFWD clears: bootstrap covers ~10/15 weed classes ≈ matches the spec's optimistic case
- If MFWD also non-commercial: 5/15 weed classes — ground-up labeling becomes the dominant source from day 1

**No public coverage (ground-up only, regardless of MFWD):**
- `cirsium` (P0), `convolvulus` (P0), `helianthus_v` (P0), `sonchus` (P1), `brassica_v` (P1), `elytrigia` (P1)
- All 3 soy disease additions (`soy_sclerotinia`, `soy_peronospora`, `soy_septoria`)
- 3 sunflower disease additions (`sunflower_sclerotinia`, `sunflower_verticillium`, `sunflower_rust`)

This is a **material narrowing** vs. the spec's "8/15 classes covered by bootstrap" claim, driven by the OPPD exclusion. Updates the planning math:
- Annotator's pre-annotation speedup applies to ~33% of classes (5/15) firmly, ~67% (10/15) if MFWD clears — not the spec's blanket "8/15".
- Ground-up labeling load is higher than the spec estimated. The annotator-budget (90 К ₽ × 12 weeks × 15 h/wk × 500 ₽/h) doesn't change; the *distribution* of where it gets spent does.

---

## Action checklist before fetching any data

1. ☐ Open Nature article on MFWD (item 6), read "Data Availability" section, record verdict in this file.
2. ☐ Verify GrowingSoy MIT scope covers the data (not just code) — open the repo's `LICENSE` and `labeled/` folder license notes.
3. ☐ Decide storage location — **not iCloud Drive** (will cause sync chaos with 10+ GB). Recommended: local `~/data/flagleaf-bootstrap/` + optional sync to Yandex Object Storage prefix `bootstrap/`.
4. ☐ For each ✅ APPROVED row, add a `data-card` entry with attribution line for any future model trained on it.
5. ☐ When new dataset candidates surface (especially for soy diseases or the 7 uncovered weed classes), open a row here *before* downloading.

# MFWD license grant — written reply from Prof. Dominik Grimm

**Received:** 29 May 2026
**From:** Prof. Dr. Dominik Grimm (`dominik.grimm@hswt.de`)
**Re:** "MFWD dataset license clarification for commercial use" (email sent 29 May 2026 — see [mfwd_license_email_draft.md](mfwd_license_email_draft.md))
**Effect:** explicit written permission for commercial use of the MFWD dataset. MFWD moves from ⏸️ PARKED / ⏳ PROVISIONAL → ✅ APPROVED in [PUBLIC_SOURCES.md item 6](PUBLIC_SOURCES.md).

---

## Reply, verbatim

> Dear Alexey,
>
> Thank you very much for your kind message and for your interest in our MFWD dataset and paper.
>
> From my side, the use you describe is fine, including commercial use, as long as our dataset and paper receive proper credit. In particular, please cite the MFWD paper in your internal data card and in any external publications, reports, documentation, or other outputs that result from the work. Where appropriate, please also acknowledge that MFWD was used for model training or pre-annotation support.
>
> To summarize, I am fine with you using a subset of MFWD for training internal computer-vision models, and with the resulting trained models being used in a commercial product, provided that the dataset itself is not redistributed and that proper attribution is given to our work.
>
> It is great to hear that the dataset may support practical weed-identification work in soybean, wheat, and sunflower.
>
> Best regards,
> Dominik

> Prof. Dr. Dominik Grimm
> Bioinformatics and Machine Learning
> Director of the HSWT site Straubing for Renewable Resources
> Vice Dean TUMCS, Information Management
> Technical University of Munich, TUM Campus Straubing for Biotechnology and Sustainability
> Petersgasse 18 | 94315 Straubing | Germany
> dominik.grimm@hswt.de

---

## What this grants — and what it requires

**Granted (binding):**
- Use a subset of MFWD for training internal CV models ✅
- Use the resulting trained models in the Flagleaf commercial product ✅
- Commercial use of the data more broadly within those bounds ✅

**Required (binding):**
1. **Do NOT redistribute the MFWD dataset itself** under any circumstances. (Trained model weights derived from MFWD are not "the dataset" and may be used in the product.)
2. **Cite the MFWD paper** in our internal data card and any external publication, report, documentation, or other output resulting from the work.
3. **Acknowledge MFWD** as used for "model training or pre-annotation support" where appropriate.

**Canonical citation to use everywhere:**

> Genze, N., Vahl, W.K., Groth, J., Wirth, M., Grieb, M. & Grimm, D.G. (2024). *Manually annotated and curated Dataset of diverse Weed Species in Maize and Sorghum for Computer Vision.* Scientific Data **11**, 109. https://doi.org/10.1038/s41597-024-02945-6

**Standard acknowledgement boilerplate** (for model documentation, internal data-card, future reports):

> Bootstrap training data for early weed-detection models in this work includes a subset of the MFWD dataset (Genze et al., *Scientific Data* 2024), used under written permission from the authors for commercial purposes with attribution. The MFWD dataset is not redistributed.

---

## Operational implications

- Use the [bootstrap_setup.md §6](bootstrap_setup.md) per-species FTP fetch with the EPPO codes for our priority weeds — chenopodium (CHEAL), galium (GALAP), polygonum (POLCO), avena (AVEFA), echinochloa (ECHCG), plus broader exposure for ambrosia (AMBEL) and amaranthus (AMARE).
- Add the citation above to a `data-card` file alongside any model trained on MFWD-derived data.
- Save this reply in the project's durable archive (iCloud or similar) in addition to the repo.

The MFWD-dependent fields in the coverage tables in [PUBLIC_SOURCES.md](PUBLIC_SOURCES.md) and [domain_shift_notes.md](domain_shift_notes.md) are now firmly approved — no "conditional" footnotes.

# Domain-shift expectations & smoke-test plan for v0

**Version:** 1.0 · 29 May 2026
**Purpose:** set realistic expectations for what v0 (the bootstrap model trained on public data) will and won't do on photos from Alekseyevka. This memo is the most important Sub-stage A deliverable — it's what tells you whether training v0 is worth doing at all, and how to interpret the result when it lands.

---

## TL;DR

v0 is a tool with a narrow job: **draw rough bounding boxes** on incoming agronomist photos so the human annotator corrects rather than draws from scratch (~1.5–2× speedup *on classes the model recognizes*). v0 will not be an agronomist replacement; it will not be production-grade; its mAP on our fields will be **30–50%**, well below the 75% kill criterion. That's by design.

The risk is that the public data we train v0 on is **so different from our actual photos** that v0 gives no useful pre-annotation at all. This memo's job is to predict how big that risk is *before* we spend 2–6 GPU hours on it.

---

## What "domain shift" means in our case

A CV model trained on data distribution A and deployed on distribution B loses accuracy proportional to how different A and B are along axes like:

| Axis | Public bootstrap data (A) | Our Alekseyevka photos (B) | Likely impact |
|---|---|---|---|
| **Camera** | DSLR / specialized rigs / handheld iPhone, UAS | Agronomist's Android phone in field, plus drone | Color profile differs ~10–15 pp mAP |
| **Soil** | German chernozem (MFWD), US prairie (North Dakota), Danish loam (OPPD — excluded), Brazilian (GrowingSoy) | Russian black soil (CBE chernozem) — closest match: MFWD if approved | Soil background contrast matters a lot for small-plant detection |
| **Crop stage / phenology** | Often early growth in trial plots | Real crop rotation at production scale: pre-emerge, tillering, jointing, heading — varies week to week | Public sources skew early-stage; mid-season weeds in mature canopy underrepresented |
| **Lighting** | Often controlled or well-lit | Phone-photo at whatever time agronomist passes — overcast, harsh midday, golden hour, drizzle | ±10 pp mAP swing typical |
| **Image framing** | Standardized (top-down, fixed height) | "Snap whatever looks weird" — variable angle, distance, crop tightness | Highest single domain-shift cost |
| **Class concept** | Pure species ID | Mixed scenes: weed + soy seedling in same frame, partial occlusion, several weed species in one box | Detection harder than classification |

The spec quantifies this honestly (§2.1.1): *"модель, обученная на щирице из Северной Дакоты с handheld камеры при ясном небе, на белгородском чернозёме с БПЛА в пасмурный день деградирует на 20–40 п.п. mAP."* That's the realistic v0 envelope.

---

## Per-class domain-shift expectation

Based on the [PUBLIC_SOURCES.md audit](PUBLIC_SOURCES.md), here's the expected v0 utility per class (assuming MFWD clears licensing):

| Our class | Bootstrap sources | Expected v0 mAP@0.5 | Why |
|---|---|---|---|
| `ambrosia` (P0) | North Dakota + 4Weed (A. trifida) + MFWD | **40–55%** | Best-covered class. Multiple sources, similar morphology across regions. North Dakota's UAS subset matches our drone capture closely. |
| `amaranthus` (P0) | North Dakota + 4Weed + MFWD + GrowingSoy (A. viridis) | **35–50%** | Well-covered but with three sister species being collapsed into one class — model may learn a too-broad concept. |
| `chenopodium` (P0) | MFWD (only — OPPD excluded) | **25–40%** if MFWD clears; **0%** otherwise | Single-source class. If MFWD's data license is non-commercial, this becomes 100% ground-up labeling at Alekseyevka. |
| `setaria` (P1) | 4Weed | **20–35%** | Small training set (139 images of S. viridis); model thin on this class. |
| `xanthium` (P2) | 4Weed | **20–35%** | Same — 159 images. |
| `echinochloa` (P1) | Multi-modal Wheat (probably) + MFWD if clears | **20–40%** | Uncertain — Multi-modal Wheat's species list not fully verified yet. |
| `galium`, `polygonum` (P2) | MFWD only | **15–35%** if MFWD clears; **0%** otherwise | OPPD was main coverage; lost. |
| `avena` (P1) | MFWD only | **15–35%** if MFWD clears; **0%** otherwise | Same. |
| `cirsium`, `convolvulus`, `helianthus_v` (all P0) | **NONE** | **0%** | Must be labeled ground-up from week 1. v0 cannot pre-annotate these — annotator works without assistance. |
| `sonchus`, `brassica_v`, `elytrigia` (P1) | **NONE** | **0%** | Same. |
| `sunflower_downy_mildew` (gap-list P0) | Mendeley sunflower | **20–40%** for leaf-close-up classification; near 0 for in-field detection | Domain shift between specimen leaf photos and in-canopy phone shots is severe. Useful as a classifier head, not a detector. |
| `sunflower_botrytis` (gap-list) | Mendeley sunflower | Same as above | Same. |
| All other diseases (wheat rust, septoria, etc.) and all stresses | **NONE** | **0%** | Ground-up labeling. |

**Headline number:** weighted by class priority (P0 weeds get most label budget), expected v0 pre-annotation coverage is **~30–40% of incoming photos getting a useful box**, optimistically. That's still a real speedup on the annotator side (each pre-annotated photo is labeled ~1.5× faster), but it's **not** a transformation of the pipeline.

If MFWD's data license clears: bump headline to ~50–60% photo coverage with useful boxes.

If MFWD also non-commercial: drop to ~20–25%. At that point, **the value of training v0 at all is marginal** — Sub-stage B should be re-evaluated; might be better to skip v0 entirely and label the first 200 photos ground-up, then jump straight to v1 fine-tuning.

---

## The cheap smoke test (run on first 20 real photos, BEFORE committing to v0 training)

This is the killer-app of Sub-stage A. Once the agronomist sends 10–20 photos (sufficient for a sanity look, even before the first "batch"):

1. Pick the **3 best-covered classes** in advance: `ambrosia`, `amaranthus`, possibly `chenopodium` if MFWD clears.
2. Pick 3–5 random photos per class from the public corpora (the ones we'd train on) and 3–5 of the agronomist's actual photos *of the same species*.
3. Sit side-by-side and rate similarity on:
   - Soil background (color, texture, surface debris)
   - Crop stage and surrounding plants
   - Camera angle (top-down vs oblique, distance)
   - Lighting (cloudy/sunny/golden-hour)
   - Plant size relative to frame

**Decision rule:**
- If 3 of 5 dimensions look very different across all 3 classes → expect v0 mAP at the low end (20–35%), reconsider whether to train v0 or skip to v1.
- If 3+ dimensions are reasonable matches in at least 2 of 3 classes → train v0 as planned. Expect mid envelope (35–50%).
- If matches are strong → expect upper envelope (45–60%) and accelerated v1 ramp.

The point: 30 minutes of human eyeball is cheaper than 2–6 hours of GPU + retraining iteration if v0 turns out useless.

---

## What we'll know that we currently don't, after Sub-stage A is fully done

1. **Whether MFWD's data is commercial-OK** — single most important unknown. ~70% of bootstrap value depends on this.
2. **Actual soil/lighting/angle delta** between our pilot fields and the public corpora — eyeball comparison, no training required.
3. **Per-class expected mAP envelope** — calibrates expectation-setting with the agronomist ("v0 will find amaranthus 4 times in 10; it won't see cirsium at all; you'll catch what it misses").
4. **Whether to train v0 at all** — the smoke test decides this *before* GPU time.

---

## What we won't know until Sub-stage B (training)

- Exact mAP per class on a real held-out set (need ≥30 labeled photos per class to measure)
- Whether class merges (multiple Amaranthus species → one class) hurt more than they help
- How much the augmentation pipeline matters (mosaic, hsv shift, hflip per spec §2.7 day-45)
- Inference latency on the deployment target (relevant only if we eventually deploy v0 anywhere — for pre-annotation in CVAT, latency doesn't matter)

---

## Honest framing for the founder / CAO conversation

If asked **"will the model help us right away?"** — the truthful answer is:

> v0 is a labor-saver for the annotator, not for the agronomist. It will draw rough boxes on roughly half of the incoming photos, the annotator corrects them faster than from scratch, and that shaves about a week of labeling time off the first 800-photo batch. The model the agronomist actually uses in the field is v3, planned for around day 90 — that's the one that needs to hit 75% mAP. v0 is plumbing for v3.

This framing protects the trust account with the CAO (no overpromise) and aligns with the kill-criterion timeline (mAP measured against v3, not v0).

# Bootstrap dataset setup — fetch & normalize for v0 training

**Trigger to run this:** when Sub-stage B fires (per [class-gap memo §B](../labeling/class_gaps_from_atlases.md) — first 10–20 real photos from the agronomist, or end of W3 fallback). Until then, only finish the prep checklist at the bottom.

Each approved dataset has a different download method and bbox format. This
doc gives copy-paste commands per source plus a unified normalization to
YOLO format for v0 training.

> **Storage:** **do not download into iCloud Drive** (~/Library/Mobile Documents/...). Use `~/data/flagleaf-bootstrap/` on local SSD. Optional: rclone-mirror to Object Storage prefix `bootstrap/` for backup.

---

## 0. One-time setup

```bash
mkdir -p ~/data/flagleaf-bootstrap/{raw,yolo,scripts}
cd ~/data/flagleaf-bootstrap

# Python env for normalization (kept outside the bot repo to avoid bloating it)
python3 -m venv .venv
source .venv/bin/activate
pip install -q ultralytics pycocotools pillow tqdm pyyaml requests
```

Sanity check disk space — total fetch estimated at **~20–40 GB** depending
on which datasets clear license (MFWD dominates if approved).

---

## 1. North Dakota Weed Dataset — CC BY 4.0 ✅

Multi-format release; pull the YOLO-format variant directly.

```bash
cd ~/data/flagleaf-bootstrap/raw
mkdir -p north-dakota && cd north-dakota
# The paper (PMC10618417) lists the dataset on Mendeley + Figshare;
# preferred mirror is Mendeley Data. Verify the current DOI before fetching —
# the dataset record's "Download all" gives a single .zip (~2–4 GB est).
echo "Open https://pmc.ncbi.nlm.nih.gov/articles/PMC10618417/ and follow the 'Data availability' link to Mendeley/Figshare."
echo "Then unzip into ./north-dakota/"
```

After download, attribution line for our data-card:

> *North Dakota Weed Image Dataset* — multi-format open-source dataset for real-time weed identification in precision agriculture (2023). Used under CC BY 4.0.

## 2. 4Weed Dataset — CC0 ✅

```bash
cd ~/data/flagleaf-bootstrap/raw
mkdir -p 4weed && cd 4weed
# OSF download via osf CLI or direct curl. Project ID: w9v3j
pip install -q osfclient
osf -p w9v3j fetch -U .   # downloads all storage providers; ~600 MB est
ls -la
```

CC0 — no attribution required, but record source in the data-card anyway.

## 3. Multi-modal Weed Dataset (wheat) — CC BY ✅

```bash
cd ~/data/flagleaf-bootstrap/raw
mkdir -p multimodal-wheat && cd multimodal-wheat
# The Frontiers paper lists dataset accessibility in its Methods section.
# Verify the current download link (often Mendeley or institutional).
echo "Open https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2022.936748/full"
echo "Section: Data Availability Statement"
```

After download, RGB-only is enough for v0 (skip depth/multi-view).

Attribution: *Xu et al., Multi-modal and multi-view image dataset for weeds detection in wheat field, Frontiers in Plant Science 2022, CC BY.*

## 4. GrowingSoy / soy-segmentation-ds — MIT ✅

```bash
cd ~/data/flagleaf-bootstrap/raw
git clone https://github.com/raulsteinmetz/soy-segmentation-ds.git
cd soy-segmentation-ds
# Confirms repo LICENSE is MIT and labels/ + augmented-labels/ are present
cat LICENSE | head -5
ls labeled augmented-labeled 2>/dev/null
```

Format is **COCO instance segmentation** (Roboflow output). Conversion to YOLO bbox format in §6.

Attribution: *Steinmetz et al., GrowingSoy dataset for weed detection in soy crops, IEEE 2024, MIT license.*

## 5. Sunflower Fruits & Leaves (Mendeley) — CC BY ✅

```bash
cd ~/data/flagleaf-bootstrap/raw
mkdir -p sunflower-mendeley && cd sunflower-mendeley
# DOI: 10.17632/b83hmrzth8.2 — Mendeley sometimes blocks direct curl; use
# the Mendeley Data web UI "Download all" if curl fails.
echo "Open https://doi.org/10.17632/b83hmrzth8.2 and click 'Download all'."
```

This is leaf-close-up imagery for *disease classification*, not in-field detection. Use as a **classification head** training set, not for bbox detection.

Attribution: *Sun Flower Fruits and Leaves dataset for Sunflower Disease Classification, Mendeley Data 2022, CC BY.*

## 6. MFWD — ⏳ HOLD UNTIL LICENSE VERIFIED

Do not run this until the data-license action item in [PUBLIC_SOURCES.md item 6](PUBLIC_SOURCES.md) is closed.

When approved, the repo's own FTP helper fetches per species:

```bash
cd ~/data/flagleaf-bootstrap/raw
git clone https://github.com/grimmlab/MFWD.git mfwd
cd mfwd
pip install -q -r requirements.txt
# EPPO codes for our priority weeds covered by MFWD:
#   AMBEL = Ambrosia artemisiifolia      (ambrosia P0)
#   AMARE = Amaranthus retroflexus       (amaranthus P0)
#   CHEAL = Chenopodium album            (chenopodium P0)
#   POLCO = Polygonum convolvulus        (polygonum P2)
#   GALAP = Galium aparine               (galium P2)
#   AVEFA = Avena fatua                  (avena P1)
#   ECHCG = Echinochloa crus-galli       (echinochloa P1)
# Plus segmentation masks for the whole subset:
python3 download_by_ftp.py species 'AMBEL,AMARE,CHEAL,POLCO,GALAP,AVEFA,ECHCG'
python3 download_by_ftp.py masks
```

MFWD's full corpus is ~94k images — the per-species pull above keeps it to ~20–30 GB.

---

## 7. Normalize everything to YOLO format

YOLOv11-m (per spec §2.7) expects a flat structure:

```
~/data/flagleaf-bootstrap/yolo/
├── images/{train,val,test}/*.jpg
├── labels/{train,val,test}/*.txt   # one .txt per image, lines: class_id cx cy w h (normalized 0-1)
└── data.yaml                        # YOLO dataset descriptor
```

Conversion sketch (one helper per source format):

- **Multi-format dataset (North Dakota)** — pull the YOLO variant directly, skip conversion.
- **OSF / Mendeley (4Weed, Multi-modal Wheat, Sunflower)** — formats vary, often Pascal VOC XML or YOLO. Convert with `ultralytics`' built-in converter or a 30-line script.
- **COCO (GrowingSoy)** — `pycocotools` → loop over annotations, convert bbox `(x, y, w, h)` to normalized `(cx, cy, w, h)`, write `.txt`.
- **MFWD** — its native format is bbox + masks per the paper's CVAT export; one converter per the repo's conventions.

A `scripts/to_yolo.py` template lives next to this file (to be written in
Sub-stage B; trivial once each source is on disk).

### Class mapping (id → our schema)

```yaml
# data.yaml — YOLO descriptor for the bootstrap corpus
path: /Users/akhaliullin/data/flagleaf-bootstrap/yolo
train: images/train
val: images/val
test: images/test

names:
  0: ambrosia
  1: amaranthus
  2: chenopodium          # ← MFWD-conditional
  3: setaria
  4: echinochloa          # ← MFWD-conditional, may stay sparse
  5: galium               # ← MFWD-conditional
  6: polygonum            # ← MFWD-conditional
  7: avena                # ← MFWD-conditional
  8: xanthium
  9: helianthus_volunteer # placeholder — no bootstrap source
  # ... remaining 6 weeds have no bootstrap source; trained from ground-up labels only
  20: sunflower_downy_mildew
  21: sunflower_botrytis
```

Source-class → our-class mapping handled in `to_yolo.py` (collapsing
*Amaranthus retroflexus* / *A. viridis* / *A. tuberculatus* → our single
`amaranthus`; sister-species *Ambrosia trifida* → our `ambrosia`; etc.).
Each merge decision recorded as a comment in the script.

---

## 8. v0 training recipe (Sub-stage B kickoff)

This is the actual training step — only run after the data is on disk *and*
the first 10–20 agronomist photos have arrived so we can sanity-check
domain shift before committing GPU time.

```bash
# YOLOv11-m fine-tune from COCO pretrained weights, ~3,000-image corpus
# Expected to take ~2–6 hours on a single GPU (or ~1 day on CPU — fine for v0)
yolo detect train \
  data=~/data/flagleaf-bootstrap/yolo/data.yaml \
  model=yolo11m.pt \
  epochs=50 \
  imgsz=720 \
  batch=16 \
  patience=10 \
  device=cpu \   # change to 0 if a GPU is available
  project=runs/v0-bootstrap \
  name=run1
```

After training:
1. Run inference on the agronomist's first 10–20 real photos.
2. Eyeball recall (boxes drawn at all?) and visual class plausibility.
3. Record observed mAP envelope — likely 30–50% per spec §2.7 expectation.
4. If usable: deploy as pre-annotator into the Stage-2 CVAT export pipeline (separately built).
5. If not usable: drop v0, label first batch ground-up, retrain after 200 photos = direct v1.

---

## Prep checklist (safe to do today, no actual downloads yet)

1. ✅ License audit complete (this file + [PUBLIC_SOURCES.md](PUBLIC_SOURCES.md))
2. ☐ Read MFWD Nature article's "Data Availability" section → record verdict in PUBLIC_SOURCES.md item 6
3. ☐ Decide storage location (recommend `~/data/flagleaf-bootstrap/`)
4. ☐ Sketch `to_yolo.py` (skeletons per source format; not run yet)
5. ☐ Read [domain_shift_notes.md](domain_shift_notes.md) before kickoff visit with agronomist

When all five are ☑ and Sub-stage B trigger fires → execute §§1–8 above.

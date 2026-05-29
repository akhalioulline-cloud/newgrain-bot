# CVAT label cheat-sheet — code → Russian name

Use these label codes in CVAT. Weeds & diseases = bounding boxes; stresses = whole-image tags.

## Weeds (15) — bounding box
- `ambrosia` — Амброзия полыннолистная (P0)
- `cirsium` — Осот полевой (P0)
- `convolvulus` — Вьюнок полевой (P0)
- `chenopodium` — Марь белая (P0)
- `amaranthus` — Щирица запрокинутая (P0)
- `setaria` — Щетинник зелёный / Мышей зелёный (P1)
- `echinochloa` — Куриное просо (P1)
- `sonchus` — Осот жёлтый (P1)
- `helianthus_v` — Падалица подсолнечника (P0)
- `brassica_v` — Падалица рапса (P1)
- `elytrigia` — Пырей ползучий (P1)
- `avena` — Овсюг (P1)
- `xanthium` — Дурнишник обыкновенный (P2)
- `galium` — Подмаренник цепкий (P2)
- `polygonum` — Горец вьюнковый (P2)

## Diseases (10) — bounding box
- `rust_brown` — Бурая ржавчина пшеницы
- `rust_yellow` — Жёлтая ржавчина
- `septoria_leaf` — Септориоз листьев
- `septoria_glume` — Септориоз колоса
- `powdery_mildew` — Мучнистая роса
- `fusarium_head` — Фузариоз колоса
- `helminthosporium` — Гельминтоспориоз
- `sunflower_phomopsis` — Фомопсис подсолнечника
- `sunflower_phoma` — Фомоз подсолнечника
- `sunflower_alternaria` — Альтернариоз подсолнечника

## Stresses (6) — whole-image tag
- `drought` — Засуха
- `waterlogging` — Переувлажнение
- `nitrogen_deficiency` — Дефицит азота
- `potassium_deficiency` — Дефицит калия
- `herbicide_damage` — Гербицидное повреждение
- `frost` — Заморозок

---

## Stage 2 MVP — manual export ↔ CVAT ↔ import loop

Stage 2 is the round-trip between our prod DB and CVAT. The two CLIs below
handle it. Both run as one-off commands streamed over SSH; no cron yet
(that's a 30-min addition for when batches are weekly+). Pre-annotation
(Stage 3) not built either — annotator draws every box for now.

### Exporting a batch (prod → CVAT zip)

```bash
ssh newgrain@158.160.46.89 \
  'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm -T bot \
   python -m labeling.export' > batch-$(date +%Y%m%d).zip
```

What lands on disk:
```
batch-YYYYMMDD.zip
├── images/{submission_id}.{ext}
└── manifest.csv  (submission_id, image, field, crop, category, species_hint, comment)
```

Side-effect on prod: every exported submission's status flips
`ready_for_labeling → in_labeling`. Re-running the export is a no-op if
no new submissions have come in.

### Annotating in CVAT Cloud

1. Open the `weeds-diseases-stress` project at app.cvat.ai.
2. `+ → Create a new task`, name `batch-YYYYMMDD`.
3. Drag the zip's `images/` folder in (or unzip the batch and upload images).
4. Open the created job → annotate using the 31-class schema above.
5. `Export Job → CVAT for images 1.1 → Download`. You'll get
   `task_<name>_xxx.zip` with `annotations.xml` inside.

The `manifest.csv` is for context only — open it in a spreadsheet to see
the agronomist's species hints and comments per photo. CVAT doesn't read it.

### Importing labels back (CVAT zip → prod)

```bash
cat task_batch-YYYYMMDD_xxx.zip | ssh newgrain@158.160.46.89 \
  'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm -T bot \
   python -m labeling.import'
```

What it does:
- Reads `annotations.xml` from the input.
- Converts pixel CVAT coords → YOLO-normalized (cx, cy, w, h ∈ [0, 1]).
- DELETEs prior labels for the affected submissions, then INSERTs the new ones
  (idempotent — safe to re-import corrections).
- Flips `in_labeling → labeled` for every submission with ≥1 box.
- Submissions with **zero** boxes (annotator left them unlabeled or flagged
  as ambiguous) stay at `in_labeling` for follow-up.

Verify with:
```bash
ssh newgrain@158.160.46.89 \
  'cd newgrain-bot && docker compose -f docker-compose.prod.yml exec -T postgres \
   psql -U newgrain -d newgrain -c "SELECT submission_id, class_label, bbox_x, bbox_y, bbox_w, bbox_h FROM labels;"'
```

### What's NOT in this MVP

- ❌ Scheduled cron (B per the Stage-2 plan) — when batches are weekly+, add 1 line to crontab.
- ❌ Pre-annotation by v0 model (C per Stage-2 plan) — needs MFWD download + v0 training first; gated on agronomist throughput becoming the bottleneck.
- ❌ Per-image annotator notes back into the bot's prod DB. The `note` column exists on `labels` but isn't populated from CVAT.
- ❌ Automatic CVAT task creation via the CVAT REST API. You create the task in the UI by hand for now.

# CVAT label cheat-sheet — code → Russian name

Use these label codes in CVAT. Weeds & diseases = bounding boxes; stresses = whole-image tags.

## Weeds (23) — bounding box
- `ambrosia` — Амброзия полыннолистная (P0)
- `cirsium` — Осот полевой / Бодяк полевой (P0)
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
- `lathyrus_tuberosus` — Чина клубненосная (tier 2 — observed once on 29 May 2026, awaiting ≥30 examples before CV training; see [schema_promotion_policy.md](schema_promotion_policy.md))
- `apera` — Метлица обыкновенная (P1)
- `lamium` — Яснотка стеблеобъемлющая (P1)
- `euphorbia` — Молочай прутьевидный (tier 2 — observed Jun 2026)
- `taraxacum` — Одуванчик лекарственный (tier 2 — observed Jun 2026)
- `artemisia` — Полынь обыкновенная (tier 2 — observed Jun 2026)
- `equisetum` — Хвощ полевой (tier 2 — observed Jun 2026)
- `polygonum_aviculare` — Спорыш / горец птичий (tier 2 — observed Jun 2026; distinct from `polygonum` = Горец вьюнковый)

## Diseases (11) — bounding box
- `rust_brown` — Бурая ржавчина пшеницы
- `rust_yellow` — Жёлтая ржавчина
- `septoria_leaf` — Септориоз листьев
- `septoria_glume` — Септориоз колоса
- `powdery_mildew` — Мучнистая роса
- `fusarium_head` — Фузариоз колоса
- `fusarium_root` — Фузариозная корневая гниль
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

## Pests / insects (15 priority) — bounding box
Priority grain-crop pests (taxonomy from the grain-pest atlas TOC — names only,
per [LICENSING.md](../LICENSING.md) §2.1). The full pest taxonomy (30 species) is
in `bot/taxonomy.py`; the other 15 are a candidate pool, picked via "Другой
вредитель" and promoted to a CVAT class on first sighting (data-driven, per
[schema_promotion_policy.md](schema_promotion_policy.md)).
- `sunn_pest` — Клоп вредная черепашка (*Eurygaster integriceps*)
- `oulema` — Пьявица красногрудая (*Oulema melanopus*)
- `anisoplia` — Хлебный жук-кузька (*Anisoplia austriaca*)
- `sitobion` — Тля злаковая большая (*Sitobion avenae*)
- `schizaphis` — Тля злаковая обыкновенная (*Schizaphis graminum*)
- `rhopalosiphum` — Тля черёмухово-злаковая (*Rhopalosiphum padi*)
- `haplothrips` — Трипс пшеничный (*Haplothrips tritici*)
- `oscinella_frit` — Шведская муха овсяная (*Oscinella frit*)
- `hessian_fly` — Гессенская муха (*Mayetiola destructor*)
- `delia_winter` — Муха озимая (*Delia coarctata*)
- `phyllotreta` — Блошка полосатая хлебная (*Phyllotreta vittula*)
- `cephus` — Пилильщик хлебный обыкновенный (*Cephus pygmaeus*)
- `agrotis_segetum` — Совка озимая (*Agrotis segetum*)
- `agriotes` — Щелкун посевной / проволочник (*Agriotes lineatus*)
- `zabrus` — Жужелица хлебная обыкновенная (*Zabrus tenebrioides*)

---

## Stage 2 MVP — manual export ↔ CVAT ↔ import loop

Stage 2 is the round-trip between our prod DB and CVAT. The two CLIs below
handle it. Both run as one-off commands streamed over SSH; no cron yet
(that's a 30-min addition for when batches are weekly+). Pre-annotation
(Stage 3) not built either — annotator draws every box for now.

### Exporting a batch — default: auto-upload to CVAT

```bash
ssh newgrain@158.160.46.89 \
  'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm bot \
   python -m labeling.export'
```

What happens:
1. Queries submissions at `status='ready_for_labeling'`.
2. Downloads photos from Object Storage.
3. Creates a new CVAT task in the `weeds-diseases-stress` project,
   named `batch-YYYYMMDD`, and uploads the images directly.
4. Flips status `ready_for_labeling → in_labeling` (only if upload succeeded).
5. Prints the task URL on stderr — click it to start annotating.

Re-running is a no-op if no new submissions have come in.
On upload failure: status NOT flipped, retry is safe.

### Exporting a batch — fallback: zip-only (CVAT unreachable / local backup)

```bash
ssh newgrain@158.160.46.89 \
  'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm -T bot \
   python -m labeling.export --zip-only' > batch-$(date +%Y%m%d).zip
```

Writes the legacy zip to stdout:
```
batch-YYYYMMDD.zip
├── images/{submission_id}.{ext}
└── manifest.csv  (submission_id, image, field, crop, category, species_hint, comment)
```

Side-effect: **does NOT flip status** (so a subsequent default-mode auto-upload
picks up the same rows). Manual upload in CVAT: `+ → Create new task` →
unzip and drag in the images.

### Annotating in CVAT Cloud

After auto-upload: click the task URL the export command printed.
Then:
1. Open the job → annotate using the 31-class schema above.
2. `Export Job → CVAT for images 1.1 → Download`. You'll get
   `task_<name>_xxx.zip` with `annotations.xml` inside.

Re-importing back (next section).

### Importing labels back — default: auto-fetch from CVAT

```bash
ssh newgrain@158.160.46.89 \
  'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm bot \
   python -m labeling.import --task <TASK_ID>'
```

The task ID is the number in the CVAT URL (e.g. `https://app.cvat.ai/tasks/2291559` → `2291559`), and is also printed by `labeling.export` when the batch is first uploaded.

What it does:
1. Triggers a server-side CVAT export.
2. Polls until the export is ready (typically 2–5 s; 5 min cap).
3. Downloads the zip directly via the API.
4. Reads `annotations.xml`, converts pixel coords → YOLO-normalized.
5. DELETEs prior labels for the affected submissions, INSERTs the new ones (idempotent — re-importing corrections is safe).
6. Flips `in_labeling → labeled` for every submission with ≥1 box. Submissions with **zero** boxes stay at `in_labeling` for follow-up.

**Why this is the default**: CVAT Cloud's UI "Export Job" button can silently fail to deliver the zip to your browser (observed on Safari/Chrome — likely pop-up blocker or session quirk). The API path is reliable.

### Importing labels back — fallback: pipe a zip on stdin

When you already have an export zip (e.g. someone else exported via the UI and sent it to you):

```bash
cat task_batch-YYYYMMDD_xxx.zip | ssh newgrain@158.160.46.89 \
  'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm -T bot \
   python -m labeling.import'
```

Same semantics, same idempotency. Just reads the zip from stdin instead of fetching it.

Verify with:
```bash
ssh newgrain@158.160.46.89 \
  'cd newgrain-bot && docker compose -f docker-compose.prod.yml exec -T postgres \
   psql -U newgrain -d newgrain -c "SELECT submission_id, class_label, bbox_x, bbox_y, bbox_w, bbox_h FROM labels;"'
```

### What's NOT in this MVP

- ❌ Scheduled cron (B per the Stage-2 plan) — when batches are weekly+, add 1 line to crontab. Auto-upload (this PR) is the prerequisite; cron is now ~30 min.
- ❌ Pre-annotation by v0 model (C per Stage-2 plan) — needs MFWD download + v0 training first; gated on agronomist throughput becoming the bottleneck.
- ❌ Per-image annotator notes back into the bot's prod DB. The `note` column exists on `labels` but isn't populated from CVAT.
- ✅ Auto-download from CVAT — `labeling.import --task <id>` triggers + polls + downloads the export via the API.

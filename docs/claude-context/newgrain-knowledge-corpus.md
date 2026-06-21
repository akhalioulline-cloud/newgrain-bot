---
name: newgrain-knowledge-corpus
description: Competitor «Андрей Тимофеевич» analysis + the CyberLeninka CC-BY agronomy-literature RAG pilot
metadata: 
  node_type: memory
  type: project
  originSessionId: b9d6a73f-b9f0-412e-b2ca-094b110c6079
---

**Competitor «Андрей Тимофеевич» (АгроТочка, ai.agrotochka.org), analysed 2026-06-19.** Free AI
agronomy assistant. Claimed corpus: 25k+ books/методички, 740k+ articles, 140k+ АПК normative
docs; "trained 3 years." Decoded: it's an **LLM + RAG over a curated RU corpus**, NOT
from-scratch training (their press doesn't state architecture; "3 years" = data collection).
Same pattern as Flagleaf's Госкаталог grounding, just a bigger corpus.

**Source licensing verdict** (can we build the same?): **CyberLeninka** ✅ open-access **CC BY**
(attribution = citing source), OAI-PMH harvestable; **official normative docs** (Минсельхоз/
Россельхознадзор/ГОСТ/Госкаталог) ✅ regulator pubs; **eLIBRARY/РИНЦ** ❌ ToS forbid bulk
download; **books/atlases** ❌ copyright (LICENSING.md §2.2 stands). So a legally-clean RAG is
buildable from CyberLeninka + official docs + Госкаталог.

**Pilot built + deployed 2026-06-19** (commits a7bf945/b3db246, doc `docs/knowledge-corpus-strategy.md`):
`agro_literature` table (migration 0026) + Russian FTS; `catalog/ingest_cyberleninka.py` (OAI-PMH
harvest + per-article abstract/year/CC-licence from page, idempotent, polite); `db.search_literature`
(OR-match significant words, ts_rank); `agro_chat._literature_grounding` cites 1–2 articles
(author/year/link), prompt forbids over-claiming. WORKS end-to-end: sunflower Q now cites a real
ВНИИМК article. LIMITS: only **36 articles** from Масличные культуры harvested — other journals hit
**HTTP 503 (rate-limiting)**; full harvest needs backoff; oilseeds-only coverage; stores
abstract+citation not full text (full-text reuse needs per-journal CC-BY verification first).
Strategic: deliberate investment, runs against Г1 "build to learn not scale" — pilot sizes value,
not a full corpus. See [[newgrain-roles-review-gate]] (agro Q&A grounding) and LICENSING.md §3.

**FULL HARVEST greenlit + running 2026-06-19 (commit dd3fd8f).** Founder: textual knowledge base
is now one of THREE parallel sub-products — (1) visual recognition, (2) CropWise sync, (3) text
knowledge base — develop in parallel (synergy: (2)+(3) keep agronomists in the bot daily → feeds
(1)'s photo metric). Production harvester `catalog/ingest_cyberleninka.py` rewritten: discovers ALL
crop-agronomy journals via OAI ListSets (**51 found**), exponential backoff on 503/429 (pilot got
rate-limited), RESUMABLE (skips ingested URLs), captures abstract + **full_text** (migration 0027,
balanced-div scan of .ocr block) + CC BY + year. Launched DETACHED on prod: `docker compose -f
docker-compose.prod.yml run -d --name cl_harvest -e PYTHONPATH=/app bot python -m
catalog.ingest_cyberleninka`. Monitor: `docker logs -f cl_harvest`. Multi-hour crawl; re-run to
resume. Bot uses `search_literature` LIVE → answers enrich as corpus fills (no redeploy).
**Resume-cron installed** (prod crontab, **02:00 + 14:00** — two gentle passes/day): `scripts/cyberleninka-refresh.sh` —
resumable + overlap-guarded (skips if a `cl_harvest*` container is running); continues unfinished
crawls + picks up newly published articles. Logs to `$HOME/cyberleninka-refresh.log`.

**Telegram notify + throttling reality (19 Jun).** Harvester notifies ADMIN_TG_IDS via
`labeling.alert.send` on each run: progress (added N) / truly-complete (records walked, skipped==0)
/ problem (records==0 can't-list, or skipped>0 throttled) / fatal error. Completion logic tracks
`records` walked so a failed run can't be reported as complete (this bug once sent a false
«собрана полностью 847»; fixed, корректировка sent). **CyberLeninka anti-bot rate-limits sustained
crawling**: when throttled it serves a 200+HTML page (not OAI XML) — `oai_records` detects missing
`<OAI-PMH>`, waits 60/120/240s, then skips. My one-off article-count probe (51 ListIdentifiers)
TRIGGERED a block — DON'T bulk-probe CyberLeninka; let the gentle crawl (delay 2.5s) + cron do it.
Stuck at 847 during the block; resumes when IP cools (cron 02:00). REVISED estimate: full corpus
likely takes MANY nightly runs (throttling caps each run), not 2–4 days — grinds out gently, bot
improves incrementally, founder notified per run.

**BLOCKED + crons PAUSED (20 Jun).** Stuck at 847 articles. CyberLeninka now serves its anti-bot
CHALLENGE PAGE for ALL requests from the VM IP 111.88.248.159 (OAI, article pages, homepage — all
~5–12KB challenge HTML, no «<OAI-PMH», captcha/«доступ» text), ~14h+ after my burst-probe flagged
the datacenter IP. Full IP-level block, sticky. The 02:00/14:00 crons kept poking it (records 0,
~100min of backoff sleeps/run), likely perpetuating the flag → **both crons commented out in the
prod crontab (`#PAUSED …`)** so the IP can go quiet. Bot runs on the 847-article pilot corpus (fine).
To get the FULL corpus: (a) request bulk/API access from CyberLeninka (open-science, CC BY — most
durable), (b) retry GENTLY from this IP in ~1 week (may have cleared), or (c) route via a residential/
proxy IP. LESSON: this source needs very gentle access — never bulk-probe it. Re-enable crons by
removing the `#PAUSED ` prefix once unblocked + rate softened. Licence
recorded in datasets/PUBLIC_SOURCES.md (CC BY; eLIBRARY + atlases excluded). Phase-2 TODO:
embeddings/pgvector over full_text for better retrieval once corpus is large.

**HARVESTED FROM FOUNDER'S MAC + LOADED (20 Jun 2026).** Block-workaround worked: ran
`scripts/cyberleninka_harvest_local.py` on the founder's Mac (residential RU IP, VPN OFF =
faster/stable; under `caffeinate -i`, nohup-detached so it survived closing Claude). Collected
**1921 articles** (92 MB JSONL w/ full_text avg ~27 KB). rsync -z --partial to server (plain scp
got "connection reset" on 92 MB over the VPN'd link — use rsync+compress for big files to the RU
VM). Loaded via `catalog.load_literature_file` (ON CONFLICT(url) DO NOTHING): **+1110 new →
agro_literature now 1957** (was 847; 811 dupes skipped). **QUALITY CAVEAT: discovery was TOO BROAD**
— the KEEP-regex matched general university «Вестник»/agri-economics bulletins whose OAI sets return
mixed content, so ~65% is OFF-TOPIC: economics ~841, medicine ~426, forestry ~207; actual field-crop
content thin (пшениц 32, подсолнечник ~5, сорняк 7, заразиха 0). BUT FTS+ts_rank keeps the noise
mostly INERT — a ranked agronomy query (сорняк|гербицид|подсолнечник) returned 5/6 relevant (lnt weed
control, sunflower phomopsis/disease, soil tillage), 1 econ slipped in. Net: modest real gain +
harmless dead weight + DB bloat. **FIX BEFORE RE-HARVEST: tighten the harvester's journal filter**
(exclude economics/medicine/multidisciplinary journals; target crop-protection/растениеводство
journals only) so re-runs (also to pick up throttled-skipped journals) add clean content. Optional:
prune the off-topic rows (founder decision — prod delete). Crons stay PAUSED.

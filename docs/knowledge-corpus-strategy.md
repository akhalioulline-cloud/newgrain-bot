# Knowledge-corpus strategy + competitor «Андрей Тимофеевич»

*2026-06-19. Why and how Flagleaf grounds its agronomy answers in real literature —
legally, neutrally — and what the «Андрей Тимофеевич» competitor actually built.*

## 1. The competitor: «Андрей Тимофеевич» (АгроТочка)

A free AI agronomy assistant at `ai.agrotochka.org` by the АгроТочка platform (named after
A.T. Болотов, founder of Russian agronomy). Marketing claim: *«обучался на базе научных
статей и методических материалов более трёх лет»*, diagnoses diseases by photo, computes
fertiliser norms, plans field work, "adapted for 70 regions."

Their stated corpus: **25,000+ books & методички, 740,000+ scientific articles & industry
publications, 140,000+ АПК normative documents**, plus crop/disease/pest/weed images and
технологические карты. They say most of the three years went into *collecting* the data.

**Decoded (honest read):** this is almost certainly an **LLM + RAG** (retrieval over a
curated corpus), not a model trained-from-scratch for three years. Their own press article
does not state the architecture; the "150 years of reading" / "3 years of training" lines are
marketing. The real, defensible asset is the **curated Russian-agronomy corpus + retrieval**.
That is the same pattern Flagleaf already uses — our Госкаталог product grounding is a small,
high-precision RAG. They simply have a much larger, broader corpus.

## 2. Can we use "that database"? Source landscape

Their specific corpus is proprietary. But the *sources* behind a corpus like that are
identifiable, and some are cleanly usable by us (the rest are not):

| Source | Scale | Usable? | Why |
|--------|-------|---------|-----|
| **CyberLeninka** | ~1M+ RU articles, incl. agronomy/plant-protection journals | ✅ **Yes** | Open-access, **CC BY** (attribution = citing the source). OAI-PMH endpoint for harvesting. |
| **Official normative docs** (Минсельхоз, Россельхознадзор, ГОСТ, Госкаталог) | the "140k docs" tier | ✅ Yes | Regulator publications — LICENSING.md §1(в). Госкаталог already in use. |
| **eLIBRARY.ru / РИНЦ** | huge (much of their "740k") | ❌ No | ToS **forbid** bulk/automated download ("запрет сплошной загрузки… роботов, пауков"). |
| **Books / методички / atlases** | the "25k books" tier | ❌ No | Copyright-sensitive — same problem as the Syngenta/Август atlases (LICENSING.md §2.2). |

**Conclusion:** we can build a comparable, *legally clean* knowledge base — chiefly from
**CyberLeninka (CC BY) + official normative docs + the Госкаталог** — and avoid eLIBRARY's ToS
and copyrighted books. This also protects the neutrality moat (open science, not one vendor).

## 3. Pilot (built 2026-06-19)

A working end-to-end slice, to prove mechanics + value before any large investment:

- **`agro_literature`** table (migration 0026) + Russian full-text index.
- **`catalog/ingest_cyberleninka.py`** — OAI-PMH harvest of agronomy journals + per-article
  abstract / year / CC-licence from the page; idempotent; polite. Stores attribution
  (title, authors, publisher, journal, year, url, license).
- **`db.search_literature`** — Russian FTS, OR-matches significant words, ranked.
- **`agro_chat._literature_grounding`** — cites 1–2 relevant articles (author, year, link);
  the prompt forbids over-claiming beyond the abstract.

**Result:** harvested **36 articles** from *Масличные культуры* (ВНИИМК — sunflower/soy).
A sunflower question now returns an answer that cites a real article, e.g.:
> *В статье «О перспективах выделения крупноплодных форм…» (Бочковой, Пивненко, 2008) —
> исследования 2006–2007 во ВНИИМК… https://cyberleninka.ru/article/n/…*

**Limits of the pilot (honest):**
- Only one journal harvested — the others returned **HTTP 503 (rate-limiting)** on the rapid
  run. A full harvest needs request backoff + longer delays.
- Coverage is oilseeds-only so far → great for подсолнечник/соя, nothing yet for wheat/weeds.
- We store **abstract + citation**, not full text. Abstract+citation+link is the low-risk use;
  full-text reuse would need per-journal CC-BY verification first.

## 4. Path to scale (if we decide to invest)

1. **Robust harvester** — exponential backoff on 503, slow crawl, resume tokens; expand the
   journal list (защита растений, земледелие, зерновые, fungal/pest journals).
2. **Per-journal licence verification** recorded in `datasets/PUBLIC_SOURCES.md` before any
   full-text ingestion (LICENSING.md default-forbidden rule).
3. **Better retrieval** — embeddings + pgvector instead of FTS, once the corpus is large.
4. **Normative docs + ВНИИ методички** as a second clean source tier.

**Stage note:** this is a deliberate investment that runs against the Г1 "build to learn, not
scale" principle — worth doing only once the photo-upload metric is proven. The pilot exists to
size the value, not to ship a full corpus today.

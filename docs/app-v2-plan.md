# Flagleaf App v2 — vision, decisions, and development plan
*Synthesis of the strategy discussion, 2 Jul 2026. Living document.*

---

## Part 1 — Summary of what we decided today

### The core reframe (the "why")
- **The current app is unloved because it asks agronomists to *feed* a tool, not *use* one** — and the one thing it could do better than them is buried behind a data-collection chore.
- **For an expert, weed recognition ≈ zero value** — he already knows the weed, faster than any app. Recognition is the value for **juniors/non-experts**; for the expert the value is the **data-grounded decision** (registered product + dose + timing/ЭПВ + ₽ savings, on *this* field) — the thing his brain can't do instantly.
- So the journey's destination moves: **recognition is the on-ramp; the decision is the reward.** "Other → I'll tell you what it is" doubles as the learning loop — the correction *is* the label, harvested from real use (no "please annotate for us").

### Who it's for (roles, blurred, full toolset to both)
1. **Young agronomists** — recognition tool (they don't know the weed).
2. **Experienced agronomists** — decision/planning + *training* (they name the weed → ground truth).
3. **The long game: a vehicle for field robotics** — see the robotics thesis below.

### Fun / wow — reconciled with the no-gamification stance
- "Fun" = **delight, wow, craft, instant reward** (point → AI answers → plan) — NOT arcade mechanics (points/badges/streaks/leaderboards), which demean professionals. The technology *is* the fun.
- **AR framing** (a reticle that locks on the plant, "hold steady / in focus") is buildable now with a generic detector — delivers wow honestly. A **live species label** (the AR-translator effect) waits for a model good enough; until then, species appears *after* capture, confidence-gated, never as fact.

### Native — via Capacitor, not two rewrites
- Wrap the existing web app in a **Capacitor** native shell: one codebase → App Store / Google Play / **RuStore**, native camera, native storage, push. Gets ~90% of "feel-real" without maintaining Swift + Kotlin.
- **Russia distribution reality:** RuStore/Android is smooth; iOS App Store in RU is hard → **TestFlight (iOS) + RuStore/APK (Android)** for the pilot.

### Offline
- Native (Capacitor) is the reliable way to work offline (PWA storage can be *evicted*; no NPU access). Storage is a **non-issue on 256 GB** — the offline core (Госкаталог + farm field data + a mobile CV model) is ~100 MB. The real limit is **RAM**, and only if you want a full on-device *LLM* offline (you don't).
- **Design:** offline = recognition + a **structured decision card** from the downloaded DB (rules, no LLM); **online = full conversational chat**. Sync-when-online keeps the DB fresh.

### Models & data (in-RU, own-specialist)
- **We use qwen3.6 (in-RU, on Yandex), not Gemini** — Gemini is geo-blocked from RU + farm-data residency (152-ФЗ). Dropping Skolkovo loosens the *strategic* "must be Russian-first" posture but **not** the technical/legal constraints for RU users; foreign models are viable for a **future non-RU market** and for **dev/benchmarking on open data** (never blocked).
- **Benchmark (16 clean iNaturalist photos):** qwen **31% species / 94% type**; gemini-2.5-pro **63% species / 94% type**. On *your* real field photos (prior paid test): Gemini ~47% vs qwen ~37%.
  - **Photo quality matters more than model choice** (Gemini 47%→63% just from clean photos) → the **camera/quality step is the single biggest accuracy lever**.
  - The **herbicide-relevant call (broadleaf/grass) is already solved at 94%** on qwen; марь белая + grass *species* are hard for everyone.
- **Accelerate the model** with the already-licensed **open-data bootstrap** (`datasets/PUBLIC_SOURCES.md`: North Dakota Weed, 4Weed, MFWD, iNaturalist/GBIF…) + a pretrained plant backbone (**transfer learning** → need hundreds of our photos, not thousands) + **qwen auto-labeling** (pre-annotate → Evgenia verifies → 3–5× throughput). This also reduces the burden on reluctant agronomists.
- **Safety rules (permanent):** never present a low-confidence guess as fact; never auto-label; in-RU inference for RU data.

### The robotics / data thesis (the north star)
- **On an autonomous machine the recognition model *is* the agronomist.** The moat in ag-robotics is the **perception layer**, not the hardware. Generic CV (~47% on field photos) is not enough → a specialized, field-validated model is the whole game.
- **Flagleaf = a regional field-perception data company** wearing an agronomist-tool coat. **Moat = RU/CIS weed×crop×stage data** the Deere/Carbon-Robotics players can't get.
- **Gaps to close for robotics-grade data:** segmentation masks (not just boxes), capture standards, growth-stage + **perspective** coverage (phone-eye ≠ drone-overhead ≠ ground-robot). Metric shifts from "photos/week" to **coverage of the priority matrix + a validated benchmark**.
- **Don't build robots — own the perception/data layer and partner** with a robotics/CV developer (co-collect robot-perspective data). **Two-horizon:** the decision-tool funds/feeds the near term; the dataset+model is the long-term asset/exit.

### Engagement / social
- **Social amplifies motivation; it doesn't create it** (Strava didn't make people run). **Value first, social second.**
- **Strava/Duolingo individual mechanics don't transfer** to a small pro team (coworker leaderboards are toxic/surveillance-flavored/demeaning to experts).
- **What does transfer:** meaningful recognition (esp. top-down from the chief; "your photo caught X / trained the model"); a **professional field-observations / discussion feed** (mentorship for juniors + peer/chief verification → *better labels* → serves the data moat); a shared team mission.
- **Team/group identity is the better social model** (future/scale): farm-vs-farm **externalizes competition** (colleagues become allies), fits farm pride + B2B, doubles as a **benchmarking product** the buyer pays for, and grows dataset diversity. Caveats: competitive privacy → **anonymized/cohort** comparison only; needs scale. **Entry via agroholdings** (intra-holding benchmarking — privacy solved). **Design the data model for it now**, build later. Individuals stay internal; only aggregates go cross-farm.

---

## Part 2 — Development plan (phased, value-first)

Guiding sequence: **value → native polish → offline/AR → social → team-social**, with **model/data as a parallel asset track** throughout. Dependencies are called out; nothing waits on the perfect model.

### Track A (parallel, ongoing) — the model & the dataset asset
- **A1.** Stand up the **open-data bootstrap**: pull the approved datasets + iNaturalist/GBIF filtered to the ЦЧР weed list; pretrained plant backbone; first fine-tune on pilot photos. Deliverable: a v0 model + a **benchmark** ("our model vs qwen vs generic CV on RU field weeds").
- **A2.** **qwen auto-labeling** in CVAT: pre-annotate each photo, Evgenia verifies/corrects (3–5× throughput). Keep the human-labeled ground truth clean (never auto-label into the training set).
- **A3.** Evolve collection toward **robotics-grade**: add **segmentation** (not just boxes), capture standards, and coverage of the **weed×crop×stage×perspective** matrix. Shift the KPI from "photos/week" to matrix coverage.
- **A4.** **Approach a robotics/CV partner early** to co-shape data and co-collect robot/drone-perspective imagery.

### Phase 1 — The re-pointed journey (web app first; the core value)
1. **Camera-first capture** — app opens toward the camera; one-thumb shoot; a snappy **framing reticle + quality/focus assistant** ("hold steady / in focus / get closer"). *(This is the biggest accuracy lever — build it even before true AR.)*
2. **Best-guess card** — capture → qwen (in-RU) → top guess + 1–2 alternatives + **"Other"**, **confidence-gated** (never a low-confidence guess as fact).
3. **The reward = the decision** — tap a guess → the streamed **field-grounded decision** (reuse `agro_chat` + Госкаталог + ЭПВ: product + dose + timing + ₽ savings for *this* field).
4. **"Other" path** — voice/text declaration → same decision + **silently logged to the CVAT flywheel** (the correction is the label).
5. **Role-aware UX** — juniors recognition-forward, experts decision/planning-forward; full toolset to both; chief review/coaching preserved.
6. **Tasteful delight** — instant-reward animation, "your correction taught the AI / поле обследовано" progress cues. No points/badges/leaderboards.
- *Mostly assembling existing parts (diagnose + agro_chat + voice + CVAT) into one beautiful flow.*

### Phase 2 — Native shell (Capacitor) + visual redesign
1. Wrap the web app in **Capacitor**; ship to **RuStore + TestFlight** (Play later).
2. **Native camera** plugin (smoother capture; foundation for AR framing).
3. Modern visual redesign (the "wow"); native push.
- *One codebase. Accounts to set up: RuStore developer, Apple Developer (TestFlight), Google Play.*

### Phase 3 — Offline-first
1. Download the **DB** (Госкаталог + farm field data) into native storage; sync-when-online.
2. **Structured decision card offline** (rules from the DB, no LLM); full chat online.
3. *(Depends on A1)* **On-device CV model** once accurate enough → offline recognition.

### Phase 4 — AR live framing
1. On-device **generic plant/leaf detector** → live reticle locks on (wow, no species needed).
2. *(Depends on A1/A3)* **Confidence-gated live species label** once the model earns it — the AR-translator effect, honestly.

### Phase 5 — Professional social layer (engagement; after value lands)
1. **Field-observations / scouting feed** tied to fields: share findings, ask, discuss.
2. **Chief coaching + recognition** in-context; mentorship channel for juniors.
3. Peer/chief verification of IDs → **better labels** (engagement = data quality).
4. Meaningful recognition + shared team mission/progress. **No individual leaderboards.**

### Phase 6 — Team / group identity + benchmarking (future/scale)
1. **Farm as a first-class social identity**; individual contributions roll *up* to the team; individuals stay internal.
2. **Anonymized / cohort benchmarking** across farms (same crop/region/scale); team standing.
3. **Entry via agroholdings** (intra-holding benchmarking — privacy solved; a bigger, faster commercial deal).
- *Design the data model for this now (Phase 1), build the surface later.*

### Cross-cutting guardrails (every phase)
- Never present a low-confidence guess as fact; never auto-label; in-RU inference for RU data (152-ФЗ + geo-block); foreign models only for non-RU market / dev / benchmarking.
- "Fun" stays delight/craft, never arcade. "Social" lives at the **team** level.
- **Two horizons:** the app (near-term value + revenue) funds and feeds the dataset+model (long-term robotics asset). Don't sacrifice one for the other.

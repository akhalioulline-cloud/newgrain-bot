# Flagleaf — Competitor / Comparable Database

A living reference of AI-agronomist / farm-chat products. Each entry uses the same schema so
it's easy to scan and compare. **Relevance to Flagleaf** is the key column — most of these are
adjacent, not head-to-head, and the *differences* tell us where our positioning is defensible.

> Positioning recap (ours): **Flagleaf** (surface-agnostic AI agronomist) + **Ear** (an
> agronomist-tailored chat we own — scouting, offline, GPS field-tagging, chief 👍/👎 = training
> signal). B2B, one farm's team, RU/ЦЧР (soy/wheat/sunflower), in-RU (qwen, 152-ФЗ), heading
> native (Expo). Moat = grounded-in-*this-farm's*-data help + workflow + delight, not raw vision.

_Last updated: 2026-07-04._

---

## 1. AgriChat.AI — climate-smart advisory via WhatsApp (SEA)
- **URL:** https://agrichat.ai · about: https://agrichat.ai/about/
- **Company / people:** Founder Suzairi Abdul Rahman (also CEO of Ipinfra); ASEAN.
- **Geography / market:** Southeast Asia (tropical smallholders + commercial farmers).
- **Delivery / platform:** **WhatsApp-exclusive** (conversational bot, no app).
- **Core value:** **Predictive, weather-first** — hyperlocal weather forecasting; weather-driven
  disease/pest *risk alerts*; smart irrigation; heat/drought action plans; harvest-window &
  nutrient timing.
- **AI / tech:** "AI prediction backed by certified LLM agronomists" (LLM-validated advice +
  climate/IoT integration). No model names, no image recognition mentioned.
- **Data approach:** Weather/climate feeds (not the farm's own visual/operational corpus).
- **Monetization:** **"Climate-triggered marketplace"** — farm inputs surface *only when* weather/
  crop conditions warrant. Needs-based, not a shop.
- **Offline / recognition / on-device:** Not mentioned (not needed for their model).
- **GTM:** B2C smallholder reach (WhatsApp ubiquity is the asset).
- **Tagline:** *"Chat. Predict. Grow — all in WhatsApp."*
- **Relevance to Flagleaf:** ⭐⭐ Adjacent, not a competitor. **The clearest real-world example of
  the strategy we rejected (bot-in-a-third-party-chat)** — and it's *right for them* because their
  value is advice + reach + commerce, where offline field-capture is irrelevant. Confirms our
  reasoning: rent the chat if the value is advice/reach; own the device if the value is field
  capture + recognition + offline (us). **Idea worth borrowing:** condition-triggered marketplace
  ≈ surfacing Госкаталог products exactly when a recognized weed/pest + ЭПВ threshold calls for it.

## 2. Agri-Chat by XSUPRA (advisor "Alora") — field-data AI advisory (DE) ⭐ closest peer
- **URL:** https://agri-chat.de (note: /en/ 404'd; base loads)
- **Company / people:** XSUPRA; AI advisor branded **"Alora"** ("Alora AI for Precision Agriculture").
- **Geography / market:** Germany/EU; available in **20 languages**. Farmers + ag professionals.
- **Delivery / platform:** **Web browser app** (no native/mobile app mentioned).
- **Core value:** **Field-data-grounded AI field advisory** — this is the one philosophically
  nearest to us. Interactive field maps + field selection; **soil-value profiles** (Bodenwert);
  **DüV-compliant fertilization documentation** (EU nitrate-directive record-keeping); satellite +
  soil mapping; weather integration; AI Q&A via Alora grounded on the farm's field data.
- **AI / tech:** "Alora" AI advisor (model unnamed) + RAG-style grounding on field/soil/satellite data.
- **Data approach:** **Uses the farm's own field data for localized recommendations** — same
  thesis as Flagleaf's field-grounding, but soil/satellite/compliance-centric rather than
  visual-recognition/scouting-centric.
- **Monetization:** Positioned as a **free AI demo/trial** (full model unknown).
- **Offline / recognition / on-device:** Not mentioned (web-only → likely online-only, no offline
  field capture; no weed/pest photo recognition surfaced).
- **Tagline:** *"KI-Feldberatung mit Alora für Landwirte"* (AI field advisory with Alora for farmers).
- **Relevance to Flagleaf:** ⭐⭐⭐ **Closest direct comparable.** Same "AI consultant grounded in
  YOUR field data" idea. **Where we differ / can win:** they're soil + satellite + EU-compliance +
  web-only; we're **visual recognition + scouting + offline + GPS field capture + team chat/verify
  loop + native**. They prove the field-grounding thesis has a market; we go deeper on the device +
  the observation→recognition→verify→learn workflow. Worth a full teardown (pricing, depth of the
  AI, whether they do any image recognition).

## 3. Farmer.CHAT — Digital Green + Gooey.AI (India/Ethiopia/Kenya)
- **URL:** https://www.help.gooey.ai/farmerchat
- **Builders:** **Gooey.AI** (AI startup) + **Digital Green** (global dev NGO), with govts of India
  & Ethiopia, FAO, Microsoft, Societal Thinking.
- **Geography / market:** India, Ethiopia, Kenya — smallholders **+ government extension agents**.
- **Delivery / platform:** **WhatsApp (primary) + Telegram + web**; text **and audio** in local
  languages (English, Hindi, Telugu, Bhojpuri, Amharic, Swahili).
- **Core value:** "Make **vetted farmer knowledge** accessible" — advisory on planting, irrigation,
  fertilization, pest control; real-time govt↔farmer comms; virtual agronomist.
- **AI / tech:** **GPT-4** + **vector DB** (RAG) on **Azure OpenAI**; corpus = editable docs +
  **1000s of best-practice videos** + call-center transcripts + vetted sources; speech via
  **Bhashini.in**; "ease of use of Google Docs."
- **Data approach:** RAG over **curated extension content + video**, not the individual farm's
  operational data or a visual-recognition corpus.
- **Monetization:** **Grant / partnership-funded** (not commercial).
- **Scale:** Digital Green — 15 yrs, **4M+ farmers**, **54,000 extension agents**, 7,000+
  location-specific videos in 40 languages; shown at UN GA (Apr 2023), FAO forum (Oct 2023).
- **Offline / recognition / on-device:** Not mentioned.
- **Tagline:** *"An AI Assistant … to make vetted farmer knowledge accessible."*
- **Relevance to Flagleaf:** ⭐⭐ Different segment (NGO/gov extension, dev-world reach) but the
  **reference architecture for RAG-over-vetted-agronomy-content**. Their moat is the *content
  corpus + reach*; ours is *this farm's data + recognition + workflow*. Useful for: multilingual
  voice, RAG design, and the "other farmers are the best source" social-knowledge idea (≈ our team
  feed). Not a market competitor to us (geography + B2C-gov).

## 4. «Андрей Тимофеевич» — RU AI-agronomist (internal intel, from our own memory)
- **URL / details:** Not fully verified here — profile from Flagleaf's internal notes.
- **Geography / market:** Russia (our market). Consumer/agronomist AI-agronomist.
- **Delivery / platform:** Chat/bot (believed Telegram-style photo-diagnosis flow).
- **Core value:** **Photo diagnosis** — send a captioned photo → structured ID + advice.
- **Where we already beat them:** they must **ask "какая культура?"** each time; Flagleaf knows
  the field's crop (from the field/GPS context), so it skips that and grounds on the actual field.
  We *borrowed* the structured-diagnosis answer format (🔬/📊/👁/🛡/⏱) from them, then grounded it.
- **Relevance to Flagleaf:** ⭐⭐⭐ **Same country + overlapping use (photo diagnosis).** The most
  direct *market* competitor we know of. TODO: verify current product, channels, pricing, whether
  they do field-grounding or offline. (See internal memory `newgrain-knowledge-corpus`,
  `newgrain-roles-review-gate`.)

---

## Also seen (not yet profiled)
- **Agrayan** (agrayan.com) — "Smart Farming & Conversational Agriculture Chatbots." Profile TBD.
- **elewashy/AgriChat** (github.com/elewashy/AgriChat) — open-source "AI-Powered Agricultural
  Assistant" (hobby/OSS, not a company). Low priority.
- **AgriChat by Nelson Sakwa** (Medium) — a conversational-UI *app concept*, not a shipped product.

## Comparison at a glance

| Product | Geo | Delivery | Core value | Farm's own data? | Recognition | Offline | Monetization |
|---|---|---|---|---|---|---|---|
| **Flagleaf/Ear (us)** | RU/ЦЧР | **Own client → native** | Field-grounded advice + scouting + recognition + team verify-loop | **Yes** | **Photo/video (qwen)** | **Yes (building on-device)** | TBD |
| AgriChat.AI | SEA | WhatsApp | Weather prediction + marketplace | No (weather) | No | No | Condition-triggered marketplace |
| Agri-Chat/Xsupra | DE/EU | Web | Field-data advisory + soil/satellite + compliance | **Yes** | Not surfaced | No | Free demo (TBD) |
| Farmer.CHAT | IN/ET/KE | WhatsApp/TG/web | RAG over vetted content + video | No (curated corpus) | No | No | Grant-funded |
| «Андрей Тимофеевич» | RU | Bot | Photo diagnosis | No (asks crop) | **Photo** | ? | ? |

## Takeaways for Flagleaf
1. **No one profiled combines all of:** the farm's own operational data + visual recognition +
   offline field capture + a team chat with a chief-verify learning loop + native. That intersection
   is our whitespace.
2. **Field-grounding is validated** (Xsupra) — but soil/compliance-centric, web-only. We own the
   *observation/recognition/scouting* angle + the *device*.
3. **The third-party-chat players** (AgriChat.AI, Farmer.CHAT) win on *reach/advice*, not *capture*.
   Reinforces: own the client because capture + offline + GPS need the device.
4. **Closest to watch:** «Андрей Тимофеевич» (same country + photo diagnosis) and **Xsupra/Alora**
   (same field-grounding thesis) — both deserve a deeper teardown.
5. **Steal-worthy ideas:** condition-triggered product surfacing (AgriChat.AI); multilingual voice +
   RAG-over-vetted-content (Farmer.CHAT); soil/satellite layers + compliance docs (Xsupra).

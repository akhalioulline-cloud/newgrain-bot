---
name: newgrain-weedid-llm-bakeoff
description: "Vision-LLM weed-ID exploration — in-RU model, Gemini geo-block, bake-off results + tooling"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5f2f4693-a1cf-4d25-9a7f-a4b71516860e
---

Exploring whether a generic multimodal LLM can suggest the weed species from a photo
(assist the agronomist / fall back when unsure) — NOT auto-label (would poison the
human-ground-truth training set). Tooling: `catalog/weedid_{export,bakeoff}.py` +
`yandex_vision_probe.py`. Test set = 31 labeled weed submissions (subcategory = label).

**Reachability (key facts):**
- **Gemini API is GEO-BLOCKED from RU** — endpoint reachable from the prod VM but Google
  returns 400 "User location is not supported." The founder's laptop VPN does NOT help the
  server (server has its own RU IP, no VPN — same lesson as the Telegram relay). Production
  Gemini would need a non-RU PROXY. Can EVALUATE it from the Mac (VPN on). Free tier ~per-day
  cap (≈60 calls exhausted it); needs billing or wait-for-reset.
- **In-RU vision model = `qwen3.6-35b-a3b`** on Yandex AI Studio (folder `b1gh24dah2ccub54lnfn`,
  OpenAI-compatible `https://llm.api.cloud.yandex.net/v1/chat/completions`, model
  `gpt://<folder>/qwen3.6-35b-a3b/latest`, image as base64 data URI). It's the ONLY multimodal
  model in this account's catalog — qwen3-235b says "not a multimodal model", yandexgpt-5-pro
  "can't see image", aliceai-flash 500'd. Sending photos to Yandex is NOT classifier-blocked
  (same trust boundary as Object Storage); sending to Google IS blocked (do it from the Mac).

**Bake-off (31 photos, DIRECTIONAL — small N):** qwen3.6 7/31 raw but ~12 were no-answers
(reasoning model burns the token budget thinking, emits no JSON even at 4000 tok) → ~37% when
it answers. Gemini ~58% on a partial run (stronger). BOTH confidently wrong on seedlings
(tiny Щирица→Марь белая) and grasses (Метлица→Овсюг); qwen3.6 conf-95 nonsense (Хвощ→Падалица
рапса). Neither authority-grade → suggestion-layer at most. Validates the human-labeling /
custom-model strategy ([[newgrain-labeling-pipeline]]).

**DECIDED 17 Jun 2026 — shelve the LLM suggestion layer for now.** Full clean bake-off
(31–32 photos, paid Gemini): **gemini-2.5-pro ≈47%**, qwen3.6 ≈37%, gemini-2.5-flash ≈33%.
All three fail the SAME way and CONFIDENTLY (conf 95–100 on wrong answers): the most
common weed Марь белая/Chenopodium (8 of 32 photos) is ~coin-flip even on pro; grasses
(Метлица/Пырей→Овсюг/Куриное просо) and broadleaf seedlings (Amaranthus↔Марь) confused.
At ~47% with high confidence on wrong calls, a pre-fill suggestion would MISLEAD the
agronomist ~as often as help → worse than nothing; never auto-label (would poison the
training set). **Plan:** keep collecting human labels for our own CV model
([[newgrain-labeling-pipeline]]); revisit LLMs in 6–12 mo or when an in-RU ag-vision
model appears. The ONE narrow low-risk use IS BUILT (17 Jun): `bot/weed_suggest.py`
(qwen3.6, in-RU) — when the agronomist taps «Другой» in the photo flow, the bot offers
≤3 ranked photo guesses as buttons (+ free-text); never auto-labels, falls back to
free-text on any failure. Handlers: `_offer_weed_suggestions` + `on_weed_suggestion`
in the PhotoForm.subcategory_other state. Gemini stays unused in prod (geo-block).

**Photo-diagnosis REFRAMED class-first for weeds (20 Jun 2026, commit 0e35c2f).** Almas reported
the bot calling марь белая «щирица» at 85%. Verified anew: qwen can't distinguish lookalike
broadleaf seedlings (марь↔щирица↔амброзия, even weed↔crop) — same photo → щирица/гречиха/горох on
different runs, stays overconfident; /no_think & reasoning_effort don't help. KEY INSIGHT: qwen
gets the CLASS (двудольный/злаковый) right even when the species is wrong, and class+crop (not
species) is what drives the registered-product list. So `bot/diagnose.py` now: (a) leads the weed
answer with «🌿 Тип сорняка: двудольный/злаковый» + grounded treatment, demotes species to a
tentative «🔍 предположительно X, возможно Y» line with the distinguishing feature (мучнистый
налёт→марь; без налёта+розовое основание→щирица); (b) grounds treatment on the CLASS not the
guessed species (synth_q «чем обработать {crop} от двудольных сорняков»); (c) caps displayed
confidence ≤60 whenever the model lists a differential (its own uncertainty signal); (d) vision
prompt carries the марь/щирица/амброзия distinguishing features. Non-weed (болезнь/вредитель/
повреждение) keep diagnosis-first format. Verified on real марь photo: «двудольный» + correct soy
broadleaf herbicides, species hedged. Correction loop: web 👎→«что не так?» captures Almas's fixes;
durable fix still the human-labeled CV model.

**qwen3.6 runaway-reasoning gotcha SOLVED for the photo-diagnosis flow (20 Jun 2026).** The
"emits no JSON / no-answer" problem is the reasoning model rambling on hidden `reasoning_content`
and never reaching the JSON `content` → `finish_reason=length` + EMPTY content → silent None.
It's UNBOUNDED: one real photo produced 36k chars of reasoning, blowing past even a 10k-token
budget. Raising `max_tokens` is a losing battle; `reasoning_effort:"low"` made it WORSE (87k
chars!); Yandex IGNORES Qwen's `/no_think`. **What works: a hard brevity DIRECTIVE in the vision
prompt** — "Отвечай БЫСТРО: рассуждай не более 1–2 коротких шагов и СРАЗУ выведи JSON". Cuts
reasoning ~10× (36k→2.8k chars, 58s→3s) and yields valid JSON. `bot/diagnose.py`: brevity line
prepended to `_VISION_SYS`, `max_tokens=8000` (now just a safety net), parse via
`JSONDecoder().raw_decode` (tolerate trailing text). Also `_prep_image` downscales ≤1536px JPEG
first: full-res phone photos via the WEB (ai.flagleaf.ru) were rejected HTTP 400 (Telegram
pre-compresses, so that path was fine). Both fixes are in shared `diagnose()` → Telegram + web.
End-to-end verified 14s, structured answer, flags «гербицидный ожог». LESSON for any new qwen3.6
call: ALWAYS include a brevity directive + downscale the image; never rely on token budget alone.

Findings that made the test work: Gemini free tier ~15–20 calls/day (quota is the
bottleneck, not the VPN once images are downscaled); the bake-off
(`catalog/weedid_bakeoff.py`) downscales photos ≤1024px + retries net/quota errors, runs
Gemini (`--gemini-model`) or Yandex qwen3.6 (`--provider yandex`); bundle built by
`weedid_export.py`. Gemini must run from the Mac via VPN (geo-block); paid tier removes
the daily cap (pennies).

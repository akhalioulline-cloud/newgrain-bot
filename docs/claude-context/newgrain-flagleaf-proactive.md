---
name: newgrain-flagleaf-proactive
description: "Flagleaf proactive (unsummoned) participation — SHADOW MODE experiment: judges but doesn't post; read the log to decide"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3441be93-9176-4fd2-9061-613379401bfe
---

**The question (founder, 5 Jul 2026):** should Flagleaf become an ACTIVE chat participant that
decides on its own when to chime in unsummoned — a short grounded punchline — not just when
@flagleaf'd? My assessment: technically easy; the hard/weak part is qwen's *restraint* (deciding
when to stay silent), not writing the line. Risk = public wrong/banal interjections erode trust +
break the Ear no-noise principle. So: **start in SHADOW MODE, decide from data.**

**Built + LIVE 5 Jul 2026 (migration 0042):**
- `bot/flagleaf.evaluate_proactive(text, history)` — ONE conservative qwen call → JSON
  `{speak, confidence, line}`. Only grounded facts/corrections (препарат/доза/норма/регламент/
  действ.вещество/ЭПВ/культура/севооборот); never chatter/opinion; skips <15-char messages.
- `wall_post`: a non-triggered human TEXT message (not media, not @flagleaf, not reply-to-bot)
  spawns a background shadow eval that **logs the would-be line and posts NOTHING**. Never blocks
  the POST.
- Table `flagleaf_shadow` (trigger_text, confidence, line); `GET /api/shadow` (admin/chief) shows
  the log + 7-day hit-rate (human_texts vs flagged). Gated by `settings.flagleaf_proactive`:
  **"shadow"** (default, current) / "off" / "live" (actually post — NOT enabled).

**How to review:** read the log directly (read-only prod ok) —
`psql -c "SELECT confidence, left(trigger_text,60), line, created_at FROM flagleaf_shadow ORDER BY created_at DESC"`.
Judge: hit-rate (how often it wants to speak vs total messages), and quality (are the lines
genuinely useful, correct, non-obvious?). **Only if the log is convincingly good** do we consider
flipping to "live" — and even then with rate-limiting + likely a private-DM-not-public-wall
option. Ties to [[newgrain-flagleaf-ear-native]], [[newgrain-weedid-llm-bakeoff]] (qwen ceiling),
[[newgrain-motivation-no-gamification]] (no-noise principle).

---
name: newgrain-motivation-no-gamification
description: "Motivation approach: loop-closing recognition + team goal, deliberately NOT points/leaderboards"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3441be93-9176-4fd2-9061-613379401bfe
---

Founder asked about gamifying photo collection (points per annotated photo, stars/ratings).
**Decision: NO gamification** — keep spec §3.3 (build to learn, not scale). Reasoning kept for
future sessions so we don't re-introduce it:

**Why not points/leaderboards (now):** the single pilot metric is "agronomist uploads 15–30 quality
photos/wk for 12 wks WITHOUT reminders" = does the tool have *intrinsic* value. Points would make us
measure point-chasing instead, contaminating that signal. Specific risks: rewards quantity over
quality (junk/common weeds farmed for points, not the rare classes the model needs); leaderboards
among ~7 coworkers at one farm are socially toxic (someone's always last in front of the boss);
extrinsic reward crowds out the organic habit we're testing. Defer real gamification to a later
SCALING phase when the question becomes "how to scale contribution".

**What we built instead (commit b583dda, Jun 2026) — recognition / loop-closing, signal-safe:**
1. Personal «ваш вклад» in app + bot `/stats`: total + `labeled` count ("🎓 уже обучают ИИ"). Private,
   no ranking. `get_user_stats` gained a `labeled` count.
2. Collective team goal (shared, not individual): `get_team_progress()` → (collected, trained);
   shown as "Команда: собрано N из M к модели" + progress bar. M = `settings.team_photo_goal`
   (default 1000, founder chose to keep 1000). New `GET /api/stats`.
3. Thank-you when a photo is annotated: `labeling/import.py` `_thank_uploaders` pushes + Telegrams the
   uploader once (grouped per person, only on first transition to `labeled`) — "🎓 Ваше фото «…» прошло
   разметку и теперь обучает ИИ". Builds on the Phase-D review push ([[newgrain-pwa]]).

If real-world rewards are ever wanted, prefer an EMPLOYER-side bonus gated on accepted/annotated
quality (HR lever), not in-app points.

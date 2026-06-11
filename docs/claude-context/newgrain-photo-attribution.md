---
name: newgrain-photo-attribution
description: "Photo upload attribution rule — Alexey's uploads always originate from Almas"
metadata: 
  node_type: memory
  type: project
  originSessionId: a3840ed9-6686-4efa-9c28-6a2134c405bf
---

**Default attribution rule (set 29 May 2026):** every submission uploaded under the founder's account (Alexey Halliullin, the bot's `Алексей Халиуллин` user) is **originated by Almas Kasumov** (CAO, anchor-farm chief agronomist). Alexey will not upload photos from any other origin — not his own, not third parties' — only Almas's.

**Why this exists:** Almas is often in the field without Telegram signal (the proxy-upload pattern). He sends photos to Alexey via WhatsApp/voice; Alexey forwards them through the bot. The bot's `submissions.user_id` records the uploader (Alexey), not the originator (Almas). This rule says: read every Alexey-uploaded row as Almas-originated.

**Where this matters:**
- `/stats` and `/history` currently attribute to the uploader. For honest reporting of the pilot success metric ("agronomist uploads 15-30 photos/week × 12 weeks") and any Series-A storytelling, combine Alexey-uploaded + Almas-uploaded counts and present them as Almas's.
- If/when a schema change adds `originator_id` to submissions, the default value for Alexey's uploads should be Almas's user_id. No need for a /uploader command — it's not user-input, it's a constant mapping.
- If the rule ever changes (Alexey starts uploading from other origins, or a second proxy is added) — update this memory.

Builds on [[newgrain-status-2026-05]], [[newgrain-labeling-pipeline]].

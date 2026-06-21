---
name: feedback-announce-entries
description: Always add an _ANNOUNCEMENTS entry when shipping a user-facing feature — /announce has lagged repeatedly
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b9d6a73f-b9f0-412e-b2ca-094b110c6079
---

When shipping a USER-FACING feature to the NewGrain bot, add a new `_ANNOUNCEMENTS` entry
in `bot/handlers.py` **in the same commit** (next sequential id; never renumber existing ones;
HTML `<b>…</b>` format, Russian, agronomist-friendly).

**Why:** `/announce` shows only items from that hardcoded list, newer than the chat's Redis
watermark. The founder has reported "new features don't appear in /announce" THREE times
(entries 6–8, then 9–11) because I shipped features without updating the list. It's a recurring
miss that erodes trust in the feature.

**How to apply:** treat the announcement entry as part of "done" for any change agronomists/
operators would notice (new flow, command, big fix). Operator-only items get a "(для оператора)"
tag, like entry 5/8. Skip it only for pure internals (infra, refactors, silent bugfixes).
The list lives at `bot/handlers.py` `_ANNOUNCEMENTS`; see [[newgrain-roles-review-gate]] for the
features themselves.

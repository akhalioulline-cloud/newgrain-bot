---
name: workflow-decisions-vs-code
description: "How the user wants us to work together — they decide, Claude implements, flag risk first"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 88a17f24-0305-4186-87de-ccb72cc8bca8
---

Division of labor: the **user makes decisions and sets up accounts**; **Claude writes the code and gives exact copy-paste commands plus how to verify them**. Explain in plain language and define jargon. Always flag the blast radius before risky or irreversible steps.

**Why:** The user is a [[user-nontechnical-founder]] who can't review code for correctness, so they rely on clear explanations and explicit verification steps, and need to understand consequences before approving destructive actions.

**How to apply:** Lead with plain-language explanation, give literal commands to paste, tell them what a successful result looks like. Before overwrites/deletes/deploys, state what could be lost and confirm.

---
name: newgrain-web-email-login
description: "Web upload (ai.flagleaf.ru/app) login by email — reg.ru SMTP, no Telegram/VPN needed"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3441be93-9176-4fd2-9061-613379401bfe
---

Agronomists log into the web photo-upload site (ai.flagleaf.ru/app, Phase 2) with a 6-digit
code → 90-day session token (Redis `flagleaf:session:<token>`, `SESSION_TTL` in api/main.py).
The code is delivered **two ways**, both landing in the same Redis slot `flagleaf:weblogin:<code>`
so `/api/auth/verify` is unchanged:
- **Telegram** `/weblogin` (needs Telegram + VPN once), and
- **Email** (no Telegram/VPN): `/api/auth/email/start` resolves the address → user, mails the code.

**Email plumbing (shipped 22 Jun 2026):**
- Sender mailbox `flagleaf@flagleaf.ru` created in **reg.ru**. SMTP = `mail.hosting.reg.ru:465` SSL.
- `bot/email_send.py` (`send_login_code`, `email_enabled`); dormant if `smtp_host` empty → page falls back to "use Telegram".
- Config keys `SMTP_HOST/PORT/USER/FROM` are non-secret → live in `.env`. `SMTP_PASSWORD` is a
  secret → in **Lockbox `flagleaf-prod`** (id e6qavh2hnlj0fr9b73sh). Add a Lockbox key via DELTA:
  `printf '[{"key":"K","text_value":"V"}]' | yc lockbox secret add-version --id <id> --payload -`
  (delta keeps all other entries — never re-submit the full payload, never read other secrets).
- Migration **0032** adds `users.email` (unique, lower()). Attach via `/myemail <addr>` (self) or
  `/setemail <tg_id> <addr>` (admin) → `set_user_email`/`get_user_by_email` in bot/db.py.
- Rate-limit 5 code-sends/IP/hr; endpoint returns generic "если адрес зарегистрирован…" (no enumeration).
- Announcement #12 covers it. See [[newgrain-web-ai]] (Phase 1 public AI demo on the same VM/nginx).

Deliverability confirmed clean to Gmail (inbox, not spam). reg.ru handles SPF; DKIM toggle in the
reg.ru panel if a provider ever spam-folders the codes.

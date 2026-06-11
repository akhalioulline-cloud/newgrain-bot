---
name: newgrain-status-2026-05
description: NewGrain/Flagleaf build status, current state, and open threads (as of 2026-06-11)
metadata: 
  node_type: memory
  type: project
  originSessionId: 88a17f24-0305-4186-87de-ccb72cc8bca8
---

**Updated 2026-06-11.** (Earlier May-25 content was superseded — Whisper→Yandex, prod deployed, etc.)

**Live in production** (Yandex Cloud VM 158.160.46.89, `docker-compose.prod.yml`): photo flow (photo → field → category → species/disease/pest → comment → S3 + `submissions` row), real pilot fields (New Grain Co), nightly backups, commands (/history /stats /fields /help /problem /finish /cancel /all /adduser /removeuser). Bot polls via the **Cloudflare relay** (`TELEGRAM_API_BASE`) to get around the RKN Telegram block.

**Voice/text — both Yandex now** (migrated OFF faster-whisper 10 Jun): RU transcription = **Yandex SpeechKit** (`bot/transcribe.py`); RU→EN translation of voice AND typed comments = **YandexGPT** (`bot/translate_llm.py`), grounded in the species dict. Needs `YC_API_KEY`+`YC_FOLDER_ID`. `comment_voice_text(_en)`, `comment_text_en` columns. **Bug fixed:** `update_submission` allowed-set had dropped `comment_voice_text`.

**Labeling pipeline** ([[newgrain-labeling-pipeline]]): CVAT Cloud, **55 labels** (23 weeds + 11 diseases + 15 pests + 6 stresses). Categories incl. disease picker + **pest picker** (`bot/taxonomy.py`; pests from Syngenta atlas TOC, names only per LICENSING.md). Nightly cron (03:30): voice backfill → export → reference-sheet deliver → import+recycle. Slot recycling fixed to detect **job state** (not task status). Annotation **reference sheet** (`labeling/reference.py`, `--deliver` → Object Storage link). Photo **dedup** at upload (`image_hash`). Dataset: ~22 labeled / 37 boxes; 3 marked `duplicate`.

**⚠️ Operational gotcha — the relay is flaky for long-poll.** getUpdates through the Cloudflare worker intermittently resets/times-out → dropped button taps → Almas's uploads stall mid-flow. Mitigations applied (10 Jun): `start_polling(polling_timeout=10)` + non-fatal `_ack()` so a stale tap still saves. **Durable fix if it recurs:** a sturdier outbound path (proxy/VPN), not the Cloudflare worker. Also: avoid rebuilding the bot while Almas is actively uploading.

**Portability kit (11 Jun):** `SETUP.md` (new-machine + workflow), `scripts/claude-memory.sh` (save/restore this memory snapshot under `docs/claude-context/`), `docs/SECRETS_LOCKBOX.md` (plan to move secrets off hand-copied `.env`).

**Open threads (pending):**
- Almas has ~6 incomplete drafts (`awaiting_metadata`) — he completes via `/finish`; `/cancel` discards. (2 complete ones were finalized 11 Jun.)
- Almas to confirm the **15-priority pest** list; note *Diuraphis noxia* (Тля ячменная = Russian wheat aphid) is in the candidate pool — maybe promote.
- **Grant docs (iCloud `Flagleaf/`): taxonomy update ON HOLD per user** until more info arrives — they should eventually say "23 сорняка, 11 болезней, **15 вредителей**, 6 стрессов". Docs already synced Whisper→Yandex SpeechKit/YandexGPT.
- **v0 bootstrap:** smoke test done 11 Jun → leans LOW end (domain gap = camera angle/lighting/framing; soil matches MFWD). v0 not worth prioritizing; **collection is the priority** (~800-frame season target; at ~22). Optional lever: a light shooting protocol for Almas.

Serves [[newgrain-goal-and-principle]].

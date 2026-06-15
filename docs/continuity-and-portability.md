# Continuity & portability

*Last updated 2026-06-15.*

This is the plan for two related futures, written so the bot survives both:

1. **Relocation / RKN isolation** — Russia cuts off the external internet (and you
   move the farm abroad at roughly the same time). The bot must be rebuildable
   *outside* Russia from things that already live outside Russia.
2. **Dual-market launch** — running an RU channel *and* a non-RU channel at the
   same time, later, as a product.

The honest summary: **the work below makes #1 survivable and makes #2 much
cheaper to start — but #2 is a larger, separate build.** What's shared between
them is *portability*: data that can live anywhere, a deploy you can repeat, and
a clear list of the few things that are wired to Russia. That shared foundation
is what we build now. The multi-region live product is built later, only when a
second market is actually real.

---

## 1. What is already safe (no action needed)

- **All code + project context** is on GitHub. Cloning the repo on any machine,
  anywhere, gives you the entire bot and these docs. This is the single most
  important continuity fact and it's already true.
- **The database** is dumped nightly (`backup.sh`, cron 03:00) to local disk
  (7-day rotation) **and** to Yandex Object Storage under `backups/`. A failed
  backup now pings the admins (the silent-outage lesson, May–Jun 2026).

What is **not** yet safe against a Russia-wide cutoff: the Yandex backups and the
photos live *inside Russia*. If Yandex becomes unreachable from abroad, they're
stranded. That's exactly what the offsite archive below fixes.

---

## 2. The cold archive (continuity copy abroad)

A continuously-updated copy of the irreplaceable data — the **photos + voice
notes** (the ML training set) and the **nightly DB dump** — pushed to a bucket
*outside* Russia. Reachable from inside Russia today, and from abroad later.

> ⚠️ Scope: this is a **disaster-recovery copy of YOUR OWN farm's data**. It is
> *not* a model for replicating *other customers'* RU personal data abroad — that
> would violate 152-ФЗ. See §5.

### Already built (inert until you provide a bucket)

| Piece | File | Behaviour with no offsite keys |
|---|---|---|
| DB dump → offsite | `backup.sh` step 3 | prints "skipping", does nothing |
| Photos/voice → offsite | `catalog/mirror_offsite.py` | prints "skipping", exits 0 |

Both read these env vars (kept in `.env`, and later in Lockbox):

```
OFFSITE_S3_ENDPOINT   # e.g. https://s3.us-west-002.backblazeb2.com  or  https://s3.amazonaws.com
OFFSITE_S3_BUCKET     # e.g. flagleaf-archive
OFFSITE_S3_ACCESS_KEY
OFFSITE_S3_SECRET_KEY
OFFSITE_S3_REGION     # e.g. us-west-002 / eu-central-1  (optional)
```

The photo mirror is **incremental** — it copies only objects not already in the
offsite bucket, so it's cheap to run nightly even as the photo set grows.

### To activate (founder + Claude)

1. **Founder:** create a bucket with an overseas provider. Two good options:
   - **Backblaze B2** — cheapest, S3-compatible, simple. Recommended for an archive.
   - **AWS S3** — pricier, but it's also where a future GCP/AWS rebuild would read
     from, so one fewer moving part if you go that way.
2. **Founder:** create an access key/secret scoped to that one bucket; give them
   to Claude (or add straight into Lockbox).
3. **Claude:** put the five `OFFSITE_S3_*` values in the server `.env` (and add
   them to Lockbox secret `flagleaf-prod` so they survive redeploys).
4. **Claude:** wire the nightly mirror into cron, right after the backup:
   ```
   30 3 * * *  cd /home/newgrain/newgrain-bot && docker compose -f docker-compose.prod.yml run --rm -T bot python -m catalog.mirror_offsite >> /home/newgrain/mirror.log 2>&1
   ```
5. **Claude:** run one full mirror by hand, then **test a restore** (download the
   latest dump from the offsite bucket, load it into a throwaway Postgres, count
   rows) so we *know* the archive is recoverable — not just that it exists.

---

## 3. Recreate-abroad runbook (the break-glass)

If Russia is cut off and you need the bot running outside Russia, this is the
whole procedure. Target: a fresh Linux VM on any provider (GCP, AWS, Hetzner, …).

1. **Clone** the repo from GitHub onto the new VM.
2. **Restore the DB**: download the latest `backups/newgrain-*.sql.gz` from the
   offsite bucket, `gunzip`, and `psql` it into a fresh Postgres (or
   `docker compose ... run postgres`). This rebuilds every field, treatment,
   submission, and NDVI row.
3. **Point storage at the offsite bucket**: set `S3_*` to the offsite bucket's
   endpoint/keys (the photos are already there, mirrored). No data movement
   needed — the archive *is* the new primary store.
4. **Swap the RU-coupled dependencies** (see §4) — mostly removing the Telegram
   relay and swapping the voice/LLM providers if their RU endpoints are gone.
5. **Bring up** the stack: `docker compose up -d --build`, then point the bot
   token's polling at the new host. Done.

Everything except step 4 is "restore from the archive." Step 4 is small and
listed explicitly below so it's never a research project under pressure.

---

## 4. The RU-coupled swap surface

These are the only places the bot is wired to Russia. Each is isolated to one
module, so a port is a swap, not a rewrite. (We are **not** refactoring these
into formal provider-adapters now — they're already cleanly separated, and
churning stable prod code for a future benefit adds risk for no present gain.
This table *is* the port plan.)

| Dependency | RU today | File(s) | Swap to, abroad |
|---|---|---|---|
| **Object storage** | Yandex Object Storage | `bot/storage.py`, `S3_*` env | AWS S3 / GCS (S3-compat) — or just keep the offsite bucket |
| **Telegram reachability** | Cloudflare relay (`TELEGRAM_API_BASE`) | `bot/net.py`, `bot/main.py` | drop the relay — Telegram is reachable directly abroad; unset the env var |
| **Voice → text** | faster-whisper, runs **in-container** | `bot/transcribe.py` | already portable — no RU dependency; runs anywhere |
| **LLM (parse ops / translate)** | YandexGPT | `bot/parse_op.py`, `bot/translate_llm.py` | Claude API (already the house model) — swap the call + key |
| **Satellite NDVI** | AWS Sentinel open mirror | `catalog/ingest_sentinel_ndvi.py` | already on AWS, not RU — reachable abroad as-is |
| **Secrets** | Yandex Lockbox | `deploy/fetch-secrets.sh` | Google Secret Manager / AWS Secrets Manager, or plain `.env` |
| **DB / Redis** | self-hosted in Docker | `docker-compose.prod.yml` | identical anywhere — no managed-service lock-in |

Notably, voice and satellite NDVI are **already** not RU-bound, and storage/DB
are provider-neutral by construction. The real porting work is two swaps
(LLM provider, drop the relay) plus pointing config at the new buckets.

---

## 5. Dual-market (RU + non-RU at the same time) — what's different

The cold archive helps a dual-market launch, but does **not** by itself make one.
What carries over vs. what's still needed:

**Carries over (the shared foundation, built now):**
- Provider-neutral data + the offsite bucket → a non-RU instance has somewhere to
  read/write that isn't Russia.
- The recreate-abroad runbook (§3) → that *is* the "stand up the non-RU instance"
  playbook.
- The swap surface (§4) → the same swaps a non-RU instance needs.
- The `farms.region` hook (migration 0021) → the column the eventual routing keys on.

**Still needed (the separate, later build):**
- **Region-aware multi-tenancy** — each farm tagged with its region; the app
  routes data and compute by region.
- **Two live stacks** running continuously (vs. one live + one cold archive) →
  ~2× ongoing ops cost and effort.
- **Bot/token strategy** — one Telegram token polls from one place, so two
  channels means two bots (two @handles) or one region-routing layer.

**The legal model (important):** dual-market is **segregate, not replicate**.
RU customers' personal data stays on RU infra (152-ФЗ); non-RU customers' data
lives abroad; the two do **not** share a data store. The cold archive copies *your
own* farm's data abroad for *your own* recovery — fine. Do **not** grow it into
copying *other* RU customers' personal data abroad; that's the line 152-ФЗ draws.

**Recommendation:** build the cold archive + keep the swap surface tidy now (this
doc). Do **not** build the dual-cloud live system until a second market is real —
that's where the real cost is, and it's cheap to defer because the foundation is
already in place.

---

## 6. What's pending (needs the founder)

- [ ] **Create the overseas bucket** (Backblaze B2 or AWS S3) + a scoped key, and
      hand the keys over. Everything in §2 activates the moment these exist.
- [ ] (then, Claude) add `OFFSITE_S3_*` to `.env` + Lockbox, wire the mirror cron,
      run the first mirror, and test a restore.

Until then, the code is shipped and inert — no behaviour change, no errors.

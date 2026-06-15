"""Proactive NDVI watch — the anti-dashboard model.

Instead of making the agronomist open a screen and read values, this scans the
pilot fields, interprets each field's recent NDVI against the same-crop norm, and
produces a SUCCINCT message that names only the fields needing a look. Run on a
weekly cron (`scripts/ndvi_watch.sh`) it delivers to admins ONLY when something
is off — silence when all is normal, so the bot earns attention rather than
spending it. Also backs the on-demand /scan command (which always replies).

Today it reads the NDVI we already have (CropWise bulk, weekly). Phase B will
feed it fresh Sentinel-2 NDVI so the weekly run reflects the latest pass.

Usage:
  python -m bot.ndvi_watch              # print the digest
  python -m bot.ndvi_watch --deliver    # send to admins, but only if anomalies
"""
import argparse
import asyncio
import sys

from bot.db import ndvi_scan


def format_digest(as_of, results) -> str:
    flagged = [r for r in results if r["lines"]]
    total = len(results)
    head = "🌱 Проверка полей (NDVI)"
    if as_of:
        head += f" — данные на {as_of:%d.%m.%Y}"
    if not flagged:
        return f"{head}\n\n✓ Все {total} полей в норме."
    out = [head, f"\n⚠️ Требуют внимания ({len(flagged)} из {total}):"]
    cap = 30  # keep the message well under Telegram's 4096-char limit
    for r in flagged[:cap]:
        # the anomaly engine already phrases each line in plain Russian
        # (e.g. "… NDVI 0.45 — ниже нормы по культуре (0.60)")
        out.append(f"\n• {r['name']} ({r['crop'] or '—'}):")
        out.append(r["lines"][0].strip())
    if len(flagged) > cap:
        out.append(f"\n…и ещё {len(flagged) - cap} полей с отклонениями (см. /scan).")
    ok = total - len(flagged)
    if ok:
        out.append(f"\nОстальные {ok} — в норме.")
    out.append("\nСтоит осмотреть отмеченные поля.")
    return "\n".join(out)


async def _run(deliver: bool) -> int:
    as_of, results = await ndvi_scan()
    digest = format_digest(as_of, results)
    print(digest)
    if deliver:
        flagged = [r for r in results if r["lines"]]
        if not flagged:
            print("ndvi_watch: all normal — nothing delivered.", file=sys.stderr)
            return 0
        from labeling.alert import send
        sent = send(digest)
        print(f"ndvi_watch: delivered to {sent} recipient(s).", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--deliver", action="store_true",
                    help="send to admins, but only when there are anomalies")
    args = ap.parse_args()
    return asyncio.run(_run(args.deliver))


if __name__ == "__main__":
    sys.exit(main())

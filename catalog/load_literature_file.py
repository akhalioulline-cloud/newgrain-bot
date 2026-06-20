"""Load a JSONL of harvested CyberLeninka articles (produced by
scripts/cyberleninka_harvest_local.py on a residential-IP Mac) into agro_literature.

Idempotent (ON CONFLICT(url) DO NOTHING). Run on the server after uploading the file:
  docker compose -f docker-compose.prod.yml run --rm -T -e PYTHONPATH=/app \
    -v /tmp/cyberleninka.jsonl:/data.jsonl bot python -m catalog.load_literature_file /data.jsonl
"""
import asyncio
import json
import sys

from sqlalchemy import text

from bot.db import engine

_SQL = text(
    "INSERT INTO agro_literature (source, journal, title, authors, publisher, year, url, "
    "license, abstract, full_text, lang) VALUES "
    "('cyberleninka', :journal, :title, :authors, :publisher, :year, :url, :license, "
    ":abstract, :full_text, :lang) ON CONFLICT (url) DO NOTHING")


async def main(path):
    inserted = read = 0
    async with engine.begin() as conn:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                read += 1
                a = json.loads(line)
                if not a.get("title") or not a.get("url"):
                    continue
                res = await conn.execute(_SQL, {
                    "journal": a.get("journal"), "title": a["title"], "authors": a.get("authors"),
                    "publisher": a.get("publisher"), "year": a.get("year"), "url": a["url"],
                    "license": a.get("license") or "CC BY", "abstract": a.get("abstract"),
                    "full_text": a.get("full_text"), "lang": a.get("lang")})
                inserted += res.rowcount
    print(f"read {read} lines, inserted {inserted} new (duplicates skipped)", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m catalog.load_literature_file <file.jsonl>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))

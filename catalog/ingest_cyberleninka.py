"""Harvest open-access (CC BY) Russian agronomy articles from CyberLeninka into the
`agro_literature` table, for grounding the chat assistant in real science (with citation).

CyberLeninka is open-access; its content is published under Creative Commons Attribution
(CC BY) — commercial use is allowed WITH attribution, which the bot provides by citing the
source (title, authors, link). This is NOT the copyrighted manufacturer atlases (those stay
banned per LICENSING.md §2.2). See docs/knowledge-corpus-strategy.md.

We take bibliographic metadata via OAI-PMH (title/authors/publisher/url) and the abstract +
publication year from the article page. Idempotent (ON CONFLICT(url) DO NOTHING). Polite:
a short delay between page fetches, and a per-journal/total cap.

Run on the prod server (RU IP reaches CyberLeninka):
  docker compose -f docker-compose.prod.yml run --rm -T -e PYTHONPATH=/app bot \
    python -m catalog.ingest_cyberleninka --max 120
"""
import argparse
import asyncio
import re
import sys
import time

import requests
from sqlalchemy import text

from bot.db import engine

OAI = "https://cyberleninka.ru/oai"
H = {"User-Agent": "Mozilla/5.0 flagleaf-research/0.1 (agronomy literature, CC-BY)"}

# Agronomy journals most relevant to our pilot crops (sunflower/soy/wheat) + general agronomy.
JOURNALS = {
    "journal_15642": "Масличные культуры",          # ВНИИМК — sunflower/soy
    "journal_30234": "Земледелие",
    "journal_17681": "Сельскохозяйственная биология",
    "journal_15389": "Агрохимический вестник",
    "journal_33169": "Научно-агрономический журнал",
}

_REC = re.compile(r"<record>(.*?)</record>", re.S)
_TOK = re.compile(r"<resumptionToken[^>]*>(.*?)</resumptionToken>", re.S)


def _tag(block, name):
    return re.findall(rf"<dc:{name}>(.*?)</dc:{name}>", block, re.S)


def _clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def oai_records(set_spec, cap):
    """Yield (title, authors, publisher, url) for a journal set, following resumptionTokens
    up to `cap` records."""
    params = {"verb": "ListRecords", "metadataPrefix": "oai_dc", "set": set_spec}
    got = 0
    while True:
        r = requests.get(OAI, params=params, timeout=60, headers=H)
        if r.status_code != 200:
            print(f"  OAI {set_spec} HTTP {r.status_code}", file=sys.stderr)
            return
        for block in _REC.findall(r.text):
            title = (_tag(block, "title") or [""])[0]
            ids = [x for x in _tag(block, "identifier") if x.startswith("http")]
            if not title or not ids:
                continue
            yield (_clean(title), "; ".join(_clean(a) for a in _tag(block, "creator")),
                   (_tag(block, "publisher") or [""])[0], ids[0])
            got += 1
            if got >= cap:
                return
        tok = _TOK.search(r.text)
        if not tok or not tok.group(1).strip():
            return
        params = {"verb": "ListRecords", "resumptionToken": tok.group(1).strip()}


def fetch_page(url):
    """Abstract + year + license from the article page. None if not clearly CC-licensed."""
    try:
        h = requests.get(url, timeout=40, headers=H).text
    except Exception:
        return None
    if "Creative Commons" not in h and "creativecommons.org" not in h:
        return None                                  # only ingest clearly CC-licensed pages
    m = re.search(r'<meta name="description" content="(.*?)"', h, re.S)
    abstract = _clean(m.group(1)) if m else None
    y = re.search(r'"datePublished"[^0-9]*(\d{4})', h) or re.search(r"Год[:\s]+(\d{4})", h)
    year = int(y.group(1)) if y else None
    lang = "ru" if abstract and len(re.findall(r"[а-яё]", abstract, re.I)) > len(abstract) // 4 else "en"
    return {"abstract": abstract, "year": year, "license": "CC BY", "lang": lang}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=80, help="max articles per journal")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between page fetches")
    a = ap.parse_args()
    inserted = skipped = 0
    async with engine.begin() as conn:
        for set_spec, jname in JOURNALS.items():
            print(f"→ {jname} ({set_spec})", file=sys.stderr)
            for title, authors, publisher, url in oai_records(set_spec, a.max):
                page = fetch_page(url)
                time.sleep(a.delay)
                if not page:
                    skipped += 1
                    continue
                res = await conn.execute(text(
                    "INSERT INTO agro_literature (source, journal, title, authors, publisher, "
                    "year, url, license, abstract, lang) VALUES "
                    "('cyberleninka', :j, :t, :au, :pub, :y, :u, :lic, :ab, :lang) "
                    "ON CONFLICT (url) DO NOTHING"),
                    {"j": jname, "t": title, "au": authors or None, "pub": publisher or None,
                     "y": page["year"], "u": url, "lic": page["license"],
                     "ab": page["abstract"], "lang": page["lang"]})
                inserted += res.rowcount
    print(f"done: inserted {inserted}, skipped(non-CC/dup) {skipped}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())

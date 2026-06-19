"""Harvest open-access (CC BY) Russian agronomy articles from CyberLeninka into the
`agro_literature` table, for grounding the chat assistant in real science (with citation).

CyberLeninka is open-access; content is published under Creative Commons Attribution (CC BY)
— commercial use is allowed WITH attribution, which the bot provides by citing the source.
This is NOT the copyrighted manufacturer atlases (those stay banned, LICENSING.md §2.2).
Licence recorded in datasets/PUBLIC_SOURCES.md. See docs/knowledge-corpus-strategy.md.

Design for the FULL harvest (tens of thousands of articles):
- Discovers all agronomy/crop-protection journals via OAI ListSets.
- Per journal: OAI ListRecords with resumptionToken; per article: page → abstract + full text
  + licence + year.
- ROBUST: exponential backoff on 503/429 (CyberLeninka throttles bursts), retries on network
  errors. RESUMABLE: skips URLs already in the table, so a re-run continues where it stopped.
- POLITE: a delay between requests (default 1.5s) to stay under the rate limit.

Long-running — run DETACHED on the prod server (RU IP):
  docker compose -f docker-compose.prod.yml run -d --name cl_harvest -e PYTHONPATH=/app \
    bot python -m catalog.ingest_cyberleninka
  docker logs -f cl_harvest        # watch progress
Re-run any time; it resumes (already-ingested URLs are skipped).
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

# Journals are kept if their NAME matches crop-agronomy domain; obvious off-domain
# (vet/zoo/economics/psychology…) simply won't match these stems.
_KEEP = re.compile(
    r"агроном|земледел|агрохим|растениевод|защит\w*\s*растен|фитопатолог|селекц|семеновод|"
    r"почвовед|масличн|зернов|овощ|плодов|виноград|кормопроизвод|мелиорац|агроинженер|"
    r"сельскохоз|аграрн|агропром|урожай|посев",
    re.I,
)
_REC = re.compile(r"<record>(.*?)</record>", re.S)
_TOK = re.compile(r"<resumptionToken[^>]*>(.*?)</resumptionToken>", re.S)

# Fallback if ListSets is rate-limited (503) — known agronomy journals, so a throttled
# discovery never zeroes the harvest. Full discovery (when ListSets works) finds more.
_FALLBACK_JOURNALS = [
    ("journal_15642", "Масличные культуры"), ("journal_30234", "Земледелие"),
    ("journal_17681", "Сельскохозяйственная биология"), ("journal_15389", "Агрохимический вестник"),
    ("journal_33169", "Научно-агрономический журнал"), ("journal_4178", "Вестник Курской ГСХА"),
    ("journal_7108", "Вестник Ульяновской ГСХА"), ("journal_9102", "Вестник Белорусской ГСХА"),
    ("journal_32785", "Известия Великолукской ГСХА"), ("journal_6014", "Вестник РУДН. Агрономия"),
    ("journal_10598", "Международный сельскохозяйственный журнал"),
    ("journal_35708", "Почвоведение и агрохимия"), ("journal_32065", "Вестник Тувинского ГУ"),
    ("journal_35035", "Сельскохозяйственные технологии"),
]


def _get(url, params=None, tries=6):
    """GET with exponential backoff on 503/429 and transient network errors."""
    delay = 8
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=50, headers=H)
            if r.status_code in (503, 429, 502, 500):
                time.sleep(delay)
                delay = min(delay * 2, 180)
                continue
            return r
        except requests.RequestException:
            time.sleep(delay)
            delay = min(delay * 2, 180)
    return None


def _tag(block, name):
    return re.findall(rf"<dc:{name}>(.*?)</dc:{name}>", block, re.S)


def _clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def discover_journals():
    r = _get(OAI, {"verb": "ListSets"}, tries=8)
    sets = re.findall(r"<setSpec>(.*?)</setSpec>\s*<setName>(.*?)</setName>", r.text, re.S) if r else []
    found = [(s, _clean(n)) for s, n in sets if s.startswith("journal_") and _KEEP.search(n)]
    if found:
        return found
    print("ListSets unavailable (throttled) — using fallback journal list", file=sys.stderr)
    return _FALLBACK_JOURNALS


def oai_records(set_spec):
    """Yield (title, authors, publisher, url) for a journal, following resumptionTokens."""
    params = {"verb": "ListRecords", "metadataPrefix": "oai_dc", "set": set_spec}
    while True:
        r = _get(OAI, params)
        if not r or r.status_code != 200:
            return
        if "<OAI-PMH" not in r.text:           # anti-bot/throttle HTML page, not OAI XML
            for w in (60, 120, 240):           # wait out a short throttle, then give up
                time.sleep(w)
                r = _get(OAI, params)
                if r and "<OAI-PMH" in r.text:
                    break
            else:
                print(f"  {set_spec}: throttled (no OAI XML) — skipping", file=sys.stderr)
                return
        for block in _REC.findall(r.text):
            title = (_tag(block, "title") or [""])[0]
            ids = [x for x in _tag(block, "identifier") if x.startswith("http")]
            if title and ids:
                yield (_clean(title), "; ".join(_clean(a) for a in _tag(block, "creator")),
                       _clean((_tag(block, "publisher") or [""])[0]), ids[0])
        tok = _TOK.search(r.text)
        if not tok or not tok.group(1).strip():
            return
        params = {"verb": "ListRecords", "resumptionToken": tok.group(1).strip()}


def _extract_ocr(html):
    """Full article text from the <div class="ocr">…</div> block (balanced-div scan)."""
    m = re.search(r'<div[^>]*class="ocr"[^>]*>', html)
    if not m:
        return None
    i, depth, n = m.end(), 1, len(html)
    start = i
    while i < n and depth:
        nxt = re.search(r"<(/?)div\b", html[i:])
        if not nxt:
            break
        i += nxt.end()
        depth += -1 if nxt.group(1) else 1
    body = _clean(html[start:i])
    return body if len(body) > 200 else None


def fetch_page(url):
    r = _get(url)
    if not r or r.status_code != 200:
        return None
    h = r.text
    if "CC BY" not in h and "Creative Commons" not in h and "creativecommons.org" not in h:
        return None                                  # only ingest clearly CC-licensed pages
    m = re.search(r'<meta name="description" content="(.*?)"', h, re.S)
    abstract = _clean(m.group(1)) if m else None
    y = re.search(r'"datePublished"[^0-9]*(\d{4})', h) or re.search(r"Год[:\s]+(\d{4})", h)
    full = _extract_ocr(h)
    txt = (abstract or "") + " " + (full or "")
    lang = "ru" if len(re.findall(r"[а-яё]", txt, re.I)) > len(txt) // 4 else "en"
    return {"abstract": abstract, "full_text": full, "year": int(y.group(1)) if y else None,
            "license": "CC BY", "lang": lang}


async def _total():
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT count(*) FROM agro_literature"))).scalar()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=2.5, help="seconds between page fetches")
    ap.add_argument("--max", type=int, default=0, help="cap per journal (0 = all)")
    ap.add_argument("--quiet", action="store_true", help="no Telegram notification")
    a = ap.parse_args()
    from labeling.alert import send as notify

    inserted = skipped = records = 0
    try:
        journals = discover_journals()
        print(f"discovered {len(journals)} agronomy journals", file=sys.stderr)
        async with engine.connect() as conn:
            seen = {r[0] for r in (await conn.execute(text("SELECT url FROM agro_literature"))).all()}
        print(f"already have {len(seen)} articles", file=sys.stderr)

        for set_spec, jname in journals:
            n_j = 0
            for title, authors, publisher, url in oai_records(set_spec):
                if a.max and n_j >= a.max:
                    break
                n_j += 1
                records += 1               # OAI records actually walked (proof we listed)
                if url in seen:
                    continue
                seen.add(url)
                page = fetch_page(url)
                time.sleep(a.delay)
                if not page or not (page["abstract"] or page["full_text"]):
                    skipped += 1
                    continue
                async with engine.begin() as conn:
                    res = await conn.execute(text(
                        "INSERT INTO agro_literature (source, journal, title, authors, publisher, "
                        "year, url, license, abstract, full_text, lang) VALUES "
                        "('cyberleninka', :j, :t, :au, :pub, :y, :u, :lic, :ab, :ft, :lang) "
                        "ON CONFLICT (url) DO NOTHING"),
                        {"j": jname, "t": title, "au": authors or None, "pub": publisher or None,
                         "y": page["year"], "u": url, "lic": page["license"],
                         "ab": page["abstract"], "ft": page["full_text"], "lang": page["lang"]})
                    inserted += res.rowcount
                if inserted and inserted % 100 == 0:
                    print(f"  …{inserted} inserted ({jname})", file=sys.stderr, flush=True)
            print(f"✓ {jname}: total inserted so far {inserted}", file=sys.stderr, flush=True)
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        if not a.quiet:
            notify(f"⚠️ Сбор научной базы (CyberLeninka) прервался ошибкой: {str(exc)[:200]}. "
                   f"Собрано статей: {await _total()}. Сбор возобновится ночью автоматически.")
        raise

    total = await _total()
    print(f"DONE: inserted {inserted}, skipped {skipped}, records {records}, total {total}",
          file=sys.stderr)
    if a.quiet:
        return
    if inserted:                       # made progress
        notify(f"📚 Научная база (CyberLeninka): прогон завершён, добавлено {inserted} "
               f"новых статей. Всего в базе: {total}. Бот уже использует их в ответах.")
    elif records == 0:                 # couldn't even list articles → access problem
        notify("⚠️ Сбор научной базы: не удалось получить список статей с CyberLeninka "
               f"(ограничение доступа). В базе пока {total}. Повтор автоматически ночью.")
    elif skipped == 0:                 # walked everything, nothing new failed → truly complete
        notify(f"✅ Научная база (CyberLeninka) собрана полностью — новых статей нет. "
               f"Всего: {total}.")
    else:                              # listed, but new pages failed to load → throttled
        notify(f"⚠️ Сбор научной базы: часть статей не загрузилась (ограничение доступа), "
               f"добавлено 0. В базе {total}. Повтор автоматически ночью.")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""Standalone CyberLeninka harvester — run on a Mac (residential IP) to avoid the
datacenter-IP block that hit the server. NO project dependencies; needs only `requests`
(pip3 install requests). Writes one JSON object per line to a .jsonl file; RESUMABLE
(skips URLs already in the file). GENTLE by design (slow + backoff) — do NOT lower the
delay or burst it, or this IP gets blocked too. See docs/cyberleninka-access.md.

  python3 scripts/cyberleninka_harvest_local.py --probe                 # test the IP
  python3 scripts/cyberleninka_harvest_local.py --out ~/cyberleninka.jsonl --max 40   # small test
  python3 scripts/cyberleninka_harvest_local.py --out ~/cyberleninka.jsonl            # full (hours)

Then upload + ingest on the server (see the doc).
"""
import argparse
import json
import os
import re
import sys
import time

import requests

OAI = "https://cyberleninka.ru/oai"
H = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15")}
KEEP = re.compile(
    r"агроном|земледел|агрохим|растениевод|защит\w*\s*растен|фитопатолог|селекц|семеновод|"
    r"почвовед|масличн|зернов|овощ|плодов|виноград|кормопроизвод|мелиорац|агроинженер|"
    r"сельскохоз|аграрн|агропром|урожай|посев", re.I)
FALLBACK = [
    ("journal_15642", "Масличные культуры"), ("journal_30234", "Земледелие"),
    ("journal_17681", "Сельскохозяйственная биология"), ("journal_15389", "Агрохимический вестник"),
    ("journal_33169", "Научно-агрономический журнал"), ("journal_4178", "Вестник Курской ГСХА"),
    ("journal_7108", "Вестник Ульяновской ГСХА"), ("journal_9102", "Вестник Белорусской ГСХА"),
    ("journal_32785", "Известия Великолукской ГСХА"), ("journal_6014", "Вестник РУДН. Агрономия"),
    ("journal_10598", "Международный сельскохозяйственный журнал"),
    ("journal_35708", "Почвоведение и агрохимия"), ("journal_32065", "Вестник Тувинского ГУ"),
    ("journal_35035", "Сельскохозяйственные технологии"),
]
_REC = re.compile(r"<record>(.*?)</record>", re.S)
_TOK = re.compile(r"<resumptionToken[^>]*>(.*?)</resumptionToken>", re.S)


def _get(url, params=None, tries=6):
    delay = 8
    for _ in range(tries):
        try:
            r = requests.get(url, params=params, timeout=50, headers=H)
            if r.status_code in (503, 429, 502, 500):
                time.sleep(delay); delay = min(delay * 2, 180); continue
            return r
        except requests.RequestException:
            time.sleep(delay); delay = min(delay * 2, 180)
    return None


def _blocked(r):
    return (not r) or ("<OAI-PMH" not in r.text)


def _tag(b, n): return re.findall(rf"<dc:{n}>(.*?)</dc:{n}>", b, re.S)
def _clean(s): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def discover():
    r = _get(OAI, {"verb": "ListSets"}, tries=8)
    if _blocked(r):
        return None
    sets = re.findall(r"<setSpec>(.*?)</setSpec>\s*<setName>(.*?)</setName>", r.text, re.S)
    found = [(s, _clean(n)) for s, n in sets if s.startswith("journal_") and KEEP.search(n)]
    return found or FALLBACK


def oai_records(spec):
    params = {"verb": "ListRecords", "metadataPrefix": "oai_dc", "set": spec}
    while True:
        r = _get(OAI, params)
        if not r or r.status_code != 200:
            return
        if "<OAI-PMH" not in r.text:
            for w in (60, 120, 240):
                time.sleep(w); r = _get(OAI, params)
                if r and "<OAI-PMH" in r.text:
                    break
            else:
                print(f"  {spec}: throttled — skipping", file=sys.stderr); return
        for b in _REC.findall(r.text):
            title = (_tag(b, "title") or [""])[0]
            ids = [x for x in _tag(b, "identifier") if x.startswith("http")]
            if title and ids:
                yield (_clean(title), "; ".join(_clean(a) for a in _tag(b, "creator")),
                       _clean((_tag(b, "publisher") or [""])[0]), ids[0])
        tok = _TOK.search(r.text)
        if not tok or not tok.group(1).strip():
            return
        params = {"verb": "ListRecords", "resumptionToken": tok.group(1).strip()}


def _extract_ocr(html):
    m = re.search(r'<div[^>]*class="ocr"[^>]*>', html)
    if not m:
        return None
    i, depth, start = m.end(), 1, m.end()
    while i < len(html) and depth:
        nxt = re.search(r"<(/?)div\b", html[i:])
        if not nxt:
            break
        i += nxt.end(); depth += -1 if nxt.group(1) else 1
    body = _clean(html[start:i])
    return body if len(body) > 200 else None


def fetch_page(url):
    r = _get(url)
    if not r or r.status_code != 200:
        return None
    h = r.text
    if "CC BY" not in h and "Creative Commons" not in h and "creativecommons.org" not in h:
        return None
    m = re.search(r'<meta name="description" content="(.*?)"', h, re.S)
    abstract = _clean(m.group(1)) if m else None
    y = re.search(r'"datePublished"[^0-9]*(\d{4})', h) or re.search(r"Год[:\s]+(\d{4})", h)
    full = _extract_ocr(h)
    txt = (abstract or "") + " " + (full or "")
    lang = "ru" if len(re.findall(r"[а-яё]", txt, re.I)) > len(txt) // 4 else "en"
    return {"abstract": abstract, "full_text": full, "year": int(y.group(1)) if y else None,
            "license": "CC BY", "lang": lang}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/cyberleninka.jsonl"))
    ap.add_argument("--delay", type=float, default=2.5)
    ap.add_argument("--max", type=int, default=0, help="cap per journal (0 = all)")
    ap.add_argument("--probe", action="store_true", help="just test if this IP is allowed")
    a = ap.parse_args()

    if a.probe:
        r = _get(OAI, {"verb": "Identify"})
        if not _blocked(r):
            print("✅ CyberLeninka доступен с этого компьютера — можно запускать сбор.")
        else:
            print("⛔ CyberLeninka блокирует и этот IP (отдаёт капчу/заглушку). Сбор отсюда не выйдет.")
        return

    seen = set()
    if os.path.exists(a.out):
        for line in open(a.out, encoding="utf-8"):
            try:
                seen.add(json.loads(line)["url"])
            except Exception:
                pass
    print(f"have {len(seen)} articles already in {a.out}", file=sys.stderr)

    journals = discover()
    if journals is None:
        print("⛔ CyberLeninka блокирует этот IP — остановитесь, пробуйте позже/с другого интернета.",
              file=sys.stderr)
        sys.exit(1)
    print(f"discovered {len(journals)} agronomy journals", file=sys.stderr)

    added = 0
    with open(a.out, "a", encoding="utf-8") as f:
        for spec, jname in journals:
            n_j = 0
            for title, authors, publisher, url in oai_records(spec):
                if a.max and n_j >= a.max:
                    break
                n_j += 1
                if url in seen:
                    continue
                seen.add(url)
                page = fetch_page(url)
                time.sleep(a.delay)
                if not page or not (page["abstract"] or page["full_text"]):
                    continue
                f.write(json.dumps({"journal": jname, "title": title, "authors": authors or None,
                                    "publisher": publisher or None, "url": url, **page},
                                   ensure_ascii=False) + "\n")
                f.flush()
                added += 1
                if added % 100 == 0:
                    print(f"  …{added} new ({jname})", file=sys.stderr, flush=True)
            print(f"✓ {jname}: {added} total new so far", file=sys.stderr, flush=True)
    print(f"DONE: {added} new articles → {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()

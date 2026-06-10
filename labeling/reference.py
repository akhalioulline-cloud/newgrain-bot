"""Annotation reference sheet — a self-contained HTML view of a batch.

CVAT shows only the (UUID) filename and a Russian species hint. To annotate
well you also need, per photo: the scientific/Latin name, Almas's voice
transcript, the field, and whether the photo is off-pilot. This builds ONE
HTML file with thumbnails embedded as base64 — open it in a browser next to
CVAT. Each card is keyed by the same filename CVAT shows
({submission_id}.{ext}), so you can match photos between the two.

Run (default = what's currently in CVAT, status=in_labeling):
  ssh newgrain@<host> 'cd newgrain-bot && docker compose -f docker-compose.prod.yml \
      run --rm -T bot python -m labeling.reference' > batch.html
Optional: --status ready_for_labeling|in_labeling|labeled  (default in_labeling)
"""
import argparse
import asyncio
import base64
import html
import io
import re
import sys

from sqlalchemy import text

from bot.config import settings
from bot.db import engine
from bot.storage import _client

THUMB_PX = 480

CATEGORY_RU = {
    "weed": "Сорняк", "disease": "Болезнь", "stress": "Стресс",
    "control": "Контроль", "treatment_result": "Результат обработки",
}


def _thumb_data_uri(image_bytes: bytes) -> str:
    from PIL import Image

    im = Image.open(io.BytesIO(image_bytes))
    im.thumbnail((THUMB_PX, THUMB_PX))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def _fetch(status):
    async with engine.connect() as conn:
        subs = (await conn.execute(text(
            """
            SELECT s.id, s.image_url, s.category, s.subcategory,
                   s.comment_text, s.comment_voice_text, s.comment_voice_text_en,
                   s.field_id, f.name AS field_name, f.crop
            FROM submissions s
            LEFT JOIN fields f ON f.id = s.field_id
            WHERE s.status = :st
            ORDER BY s.created_at
            """
        ), {"st": status})).mappings().all()
        species = (await conn.execute(text(
            "SELECT latin_name, russian_name, common_aliases, cvat_code FROM weed_species"
        ))).mappings().all()
    return subs, species


def _norm(s: str) -> str:
    """Normalize a species string for matching: lowercase, trim surrounding
    whitespace and trailing punctuation (agronomists type 'Дурнишник.' etc.)."""
    return (s or "").strip().strip(" .,;:!").lower()


def _scan_species(textval, lut):
    """Find species the agronomist named in a voice/text note, by matching the
    species dictionary against the transcript — exact, unlike a loose MT of a
    weed name. Returns deduped (latin, russian, code) records."""
    if not textval:
        return []
    t = " " + textval.lower() + " "
    found = {}
    for k, rec in lut.items():
        if len(k) >= 4 and k in t:
            found[rec[0]] = rec  # dedupe by Latin name
    return list(found.values())


def _species_lookup(species_rows):
    """Map any stored hint (Latin pick, Russian name, or alias) → (latin, russian)."""
    lut = {}
    for s in species_rows:
        rec = (s["latin_name"], s["russian_name"], s["cvat_code"])
        lut[_norm(s["latin_name"])] = rec
        lut[_norm(s["russian_name"])] = rec
        for a in (s["common_aliases"] or []):
            lut[_norm(a)] = rec
    return lut


def _render(subs, lut, status) -> str:
    cards = []
    for r in subs:
        ext = (r["image_url"].rsplit(".", 1)[-1] if "." in r["image_url"] else "jpg")
        fname = f"{r['id']}.{ext}"           # exactly what CVAT shows
        s3_key = r["image_url"].replace(f"s3://{settings.s3_bucket}/", "")
        try:
            img = _client.get_object(Bucket=settings.s3_bucket, Key=s3_key)["Body"].read()
            thumb = _thumb_data_uri(img)
        except Exception as exc:
            thumb = ""
            print(f"thumb failed for {fname}: {exc}", file=sys.stderr)

        # Field / off-pilot badge
        if r["field_id"] is None:
            field_html = '<span class="badge off">ВНЕ ПИЛОТА</span>'
        else:
            crop = f" · {html.escape(r['crop'])}" if r["crop"] else ""
            field_html = f'<span class="badge field">{html.escape(r["field_name"] or "поле?")}{crop}</span>'

        # Species: raw hint + resolved Latin/Russian (the "English"/scientific name)
        hint = (r["subcategory"] or "").strip()
        sp_html = '<span class="muted">— вид не указан —</span>'
        if hint:
            rec = lut.get(_norm(hint))
            if not rec:
                # Compound hints ("Спорыш / горец птичий", "Молокан, или молочай")
                # — try each part.
                for part in re.split(r"\s*[/,;]\s*|\s+или\s+", hint):
                    rec = lut.get(_norm(part))
                    if rec:
                        break
            if rec:
                latin, ru, code = rec
                code_html = (f' <span class="code">→ метка CVAT: {html.escape(code)}</span>'
                             if code else
                             ' <span class="warn">(нет CVAT-класса — пропустить)</span>')
                # If we interpreted/normalized the hint, show the agronomist's
                # original wording so the annotator can sanity-check.
                orig = ""
                if _norm(hint) not in (_norm(ru), _norm(latin)):
                    orig = f' <span class="muted">· агроном: «{html.escape(hint)}»</span>'
                sp_html = (f'<b>{html.escape(latin)}</b> '
                           f'<span class="muted">({html.escape(ru)})</span>{code_html}{orig}')
            else:
                sp_html = (f'{html.escape(hint)} '
                           f'<span class="warn">(не в словаре — уточнить/пропустить)</span>')

        cat = CATEGORY_RU.get(r["category"], r["category"] or "—")
        voice = (r["comment_voice_text"] or "").strip()
        voice_en = (r["comment_voice_text_en"] or "").strip()
        comment = (r["comment_text"] or "").strip()
        meta = [f'<div class="row"><span class="k">Поле:</span> {field_html}</div>',
                f'<div class="row"><span class="k">Категория:</span> {html.escape(cat)}</div>',
                f'<div class="row"><span class="k">Вид (подсказка):</span> {sp_html}</div>']
        if voice:
            block = f'<span class="k">🎤 Голос (RU):</span> {html.escape(voice)}'
            if voice_en:
                block += f'<br><span class="k">🇬🇧 Voice (EN):</span> {html.escape(voice_en)}'
            # Exact species named in the voice note, matched against the dictionary.
            named = _scan_species(voice, lut)
            if named:
                tags = ", ".join(
                    f'<b>{html.escape(la)}</b>' + (f' <span class="code">{co}</span>' if co else '')
                    for la, ru, co in named)
                block += f'<br><span class="k">🔬 В голосе вид:</span> {tags}'
            meta.append(f'<div class="row voice">{block}</div>')
        if comment:
            meta.append(f'<div class="row"><span class="k">💬 Текст:</span> '
                        f'{html.escape(comment)}</div>')

        cards.append(f"""
        <div class="card">
          <img src="{thumb}" alt="{fname}">
          <div class="meta">
            <div class="fname">{fname}</div>
            {''.join(meta)}
          </div>
        </div>""")

    css = """
    body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1a1a1a;background:#faf8f4}
    h1{font-size:20px} .sub{color:#666;margin-bottom:18px}
    .card{display:flex;gap:16px;border:1px solid #ddd;border-radius:10px;padding:14px;margin-bottom:14px;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.04)}
    .card img{width:300px;height:300px;object-fit:cover;border-radius:8px;background:#eee;flex:none}
    .meta{flex:1} .fname{font-family:Menlo,monospace;font-size:12px;color:#888;margin-bottom:8px;word-break:break-all}
    .row{margin:5px 0;font-size:15px} .k{color:#888;display:inline-block;min-width:120px}
    .voice{background:#fff7e6;border-left:3px solid #d4a04e;padding:6px 8px;border-radius:4px}
    .badge{padding:2px 8px;border-radius:6px;font-weight:600;font-size:13px}
    .badge.field{background:#e6f0e6;color:#2e5e2e} .badge.off{background:#fde0e0;color:#a11}
    .muted{color:#888} .warn{color:#c0392b;font-weight:600}
    .code{font-family:Menlo,monospace;background:#eef3ff;color:#1a4fa0;padding:1px 6px;border-radius:5px;font-size:13px;font-weight:600}
    """
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
    <title>Flagleaf — справочник разметки</title><style>{css}</style></head><body>
    <h1>Flagleaf — справочник для разметки</h1>
    <div class="sub">Статус: {html.escape(status)} · фото: {len(subs)}. Имя файла совпадает с тем, что показывает CVAT.</div>
    {''.join(cards)}
    </body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--status", default="in_labeling",
                    help="submission status to include (default: in_labeling)")
    ap.add_argument("--deliver", action="store_true",
                    help="send the HTML to ADMIN_TG_IDS via Telegram instead of stdout")
    args = ap.parse_args()

    subs, species = asyncio.run(_fetch(args.status))
    if not subs:
        print(f"No submissions at status={args.status!r}.", file=sys.stderr)
        return 1
    print(f"Building reference for {len(subs)} photo(s) at status={args.status!r}…",
          file=sys.stderr)
    lut = _species_lookup(species)
    html_doc = _render(subs, lut, args.status)

    if args.deliver:
        # Host the HTML in Object Storage (RU, reachable from the annotator's
        # browser) and send a short download link via the text alert. Pushing
        # the ~1 MB file itself through the Telegram relay fails (SSL reset on
        # large uploads); a short URL goes through fine.
        from bot.storage import put_object_sync, presigned_url
        from labeling.alert import send

        key = f"reference/flagleaf-reference-{args.status}.html"
        put_object_sync(key, html_doc.encode("utf-8"), "text/html; charset=utf-8")
        url = presigned_url(key)
        n = send(
            f"📋 Справочник для разметки готов: {len(subs)} фото (статус {args.status}).\n"
            f"Откройте в браузере рядом с CVAT (ссылка действует 7 дней):\n{url}"
        )
        print(f"reference uploaded; link sent to {n} admin(s).", file=sys.stderr)
        return 0 if n else 2

    sys.stdout.write(html_doc)
    print("done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

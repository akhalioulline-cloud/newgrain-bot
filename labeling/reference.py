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
                   s.comment_text, s.comment_voice_text,
                   s.field_id, f.name AS field_name, f.crop
            FROM submissions s
            LEFT JOIN fields f ON f.id = s.field_id
            WHERE s.status = :st
            ORDER BY s.created_at
            """
        ), {"st": status})).mappings().all()
        species = (await conn.execute(text(
            "SELECT latin_name, russian_name, common_aliases FROM weed_species"
        ))).mappings().all()
    return subs, species


def _norm(s: str) -> str:
    """Normalize a species string for matching: lowercase, trim surrounding
    whitespace and trailing punctuation (agronomists type 'Дурнишник.' etc.)."""
    return (s or "").strip().strip(" .,;:!").lower()


def _species_lookup(species_rows):
    """Map any stored hint (Latin pick, Russian name, or alias) → (latin, russian)."""
    lut = {}
    for s in species_rows:
        pair = (s["latin_name"], s["russian_name"])
        lut[_norm(s["latin_name"])] = pair
        lut[_norm(s["russian_name"])] = pair
        for a in (s["common_aliases"] or []):
            lut[_norm(a)] = pair
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
            pair = lut.get(_norm(hint))
            if pair:
                latin, ru = pair
                sp_html = (f'<b>{html.escape(latin)}</b> '
                           f'<span class="muted">({html.escape(ru)})</span>')
            else:
                sp_html = (f'{html.escape(hint)} '
                           f'<span class="warn">(не в словаре — уточнить)</span>')

        cat = CATEGORY_RU.get(r["category"], r["category"] or "—")
        voice = (r["comment_voice_text"] or "").strip()
        comment = (r["comment_text"] or "").strip()
        meta = [f'<div class="row"><span class="k">Поле:</span> {field_html}</div>',
                f'<div class="row"><span class="k">Категория:</span> {html.escape(cat)}</div>',
                f'<div class="row"><span class="k">Вид (подсказка):</span> {sp_html}</div>']
        if voice:
            meta.append(f'<div class="row voice"><span class="k">🎤 Голос:</span> '
                        f'{html.escape(voice)}</div>')
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
    args = ap.parse_args()

    subs, species = asyncio.run(_fetch(args.status))
    if not subs:
        print(f"No submissions at status={args.status!r}.", file=sys.stderr)
        return 1
    print(f"Building reference for {len(subs)} photo(s) at status={args.status!r}…",
          file=sys.stderr)
    lut = _species_lookup(species)
    sys.stdout.write(_render(subs, lut, args.status))
    print("done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

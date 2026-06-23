"""Draft 'product playbook' for the chief agronomist to review.

What the farm ACTUALLY applies per crop (from CropWise: product, typical dose, frequency,
active substance) cross-referenced with the Госкаталог registered spectrum — so Almas just
reviews and corrects (against which weeds, what dose) and fills in his ЭПВ, instead of writing
his whole scheme from scratch. Outputs a self-contained HTML to stdout; render to PDF.

    docker compose -f docker-compose.prod.yml run --rm -T bot python -m catalog.product_playbook > playbook.html
"""
import asyncio
import html
import re
import sys

from sqlalchemy import text

from bot.db import _catalog_stem, engine, get_farm_products_for_crop

FARM = 1
CROPS = ["Соя", "Подсолнечник", "Пшеница", "Ячмень", "Кукуруза"]
ADJUVANT = re.compile(r"адью|биолипостим|тренд|прилипат|\bпав\b", re.I)


def _brand(p: str) -> str:
    return re.split(r"[ ,]", (p or "").strip())[0]


async def _catalog_targets(conn, product: str, stem: str):
    rows = (await conn.execute(text(
        "SELECT DISTINCT target, rate FROM pesticide_applications "
        "WHERE product_name ILIKE :b AND crop ILIKE :s AND status = 'Действует' "
        "ORDER BY target LIMIT 8"),
        {"b": f"%{_brand(product)}%", "s": f"%{stem}%"})).mappings().all()
    targets = "; ".join(sorted({(r["target"] or "").strip() for r in rows if r["target"]}))
    rate = next((r["rate"] for r in rows if r["rate"]), "")
    return targets[:180], rate


async def main() -> int:
    parts = []
    async with engine.connect() as conn:
        for crop in CROPS:
            prods = await get_farm_products_for_crop(FARM, crop, limit=20)
            if not prods:
                continue
            stem = _catalog_stem(crop) or crop
            rows = []
            for r in prods:
                targets, rate = await _catalog_targets(conn, r["product"], stem)
                adj = " <span class='adj'>(добавка?)</span>" if ADJUVANT.search(r["product"] or "") else ""
                rows.append(
                    f"<tr><td>{html.escape(r['product'])}{adj}</td>"
                    f"<td>{html.escape((r['active_substance'] or '')[:55])}</td>"
                    f"<td>{html.escape(targets) or '—'}</td>"
                    f"<td>{html.escape(r['typ_dose'] or '?')}</td>"
                    f"<td>{html.escape(rate or '—')}</td>"
                    f"<td class='c'>{r['passes']}</td></tr>")
            parts.append(
                f"<h2>{html.escape(crop)}</h2>"
                "<table><tr><th>Препарат</th><th>Д.в. (CropWise)</th>"
                "<th>Против чего (Госкаталог)</th><th>Норма хоз-ва</th><th>Норма каталог</th><th>Обр.</th></tr>"
                + "".join(rows) + "</table>"
                "<p class='epv'><b>ЭПВ (впишите, пожалуйста):</b> _____________________________________________</p>")
    print(_TEMPLATE.replace("{{BODY}}", "".join(parts)))
    return 0


_TEMPLATE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>
  @page { size: A4; margin: 15mm 14mm; }
  body { font-family: "Helvetica Neue", Arial, sans-serif; color:#1f1f1f; font-size:10pt; line-height:1.4; }
  .logo { font-size:18pt; font-weight:800; letter-spacing:.12em; } .logo b { color:#b08d38; }
  h1 { font-size:15pt; margin:2mm 0 1mm; } .sub { color:#555; font-size:10pt; margin:0 0 3mm; }
  .intro { background:#faf6ec; border-left:3px solid #b08d38; padding:3mm 4mm; font-size:9.6pt; margin:3mm 0 4mm; }
  h2 { font-size:12pt; color:#6b541f; margin:6mm 0 1mm; page-break-after:avoid; }
  table { width:100%; border-collapse:collapse; margin:1mm 0 2mm; font-size:9pt; page-break-inside:auto; }
  th,td { text-align:left; padding:1.5mm 2mm; border-bottom:1px solid #e3ddd0; vertical-align:top; }
  th { background:#f6f1e6; color:#6b541f; } td.c { text-align:center; }
  .adj { color:#c0392b; font-size:8pt; }
  .epv { font-size:9.4pt; margin:1mm 0 4mm; }
  footer { margin-top:5mm; border-top:1px solid #e3ddd0; padding-top:2mm; color:#999; font-size:8.5pt; text-align:center; }
</style></head><body>
<div class="logo">FLAG<b>LEAF</b></div>
<h1>Схема препаратов хозяйства — черновик на проверку</h1>
<p class="sub">Собрано из CropWise (что реально применяете) + Госкаталог (зарегистрированное назначение) · АО «НЗК»</p>
<div class="intro">Алмас, это <b>не нужно выписывать заново</b> — мы собрали из Ваших же записей CropWise, чем и
в каких нормах хозяйство реально работает по каждой культуре, и сопоставили с Госкаталогом (против чего препарат
зарегистрирован). Просьба: <b>проверьте и поправьте</b> — против какого спектра, в какой норме; отметьте, что
лишнее (прилипатели/адъюванты помечены «добавка?»), чего не хватает. И, пожалуйста, впишите <b>ЭПВ</b> по
каждой культуре — этого в CropWise нет, и знаете только Вы.</div>
{{BODY}}
<footer>Flagleaf · АО «НЗК» · черновик схемы препаратов · 2026</footer>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

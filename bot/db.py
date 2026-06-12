from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bot.config import settings
from bot.moa import moa_lines, ndvi_anomaly_samecrop

engine = create_async_engine(settings.database_url, pool_pre_ping=True)


async def get_active_user(tg_id: int):
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, tg_user_id, full_name, phone, farm_id, role "
                "FROM users WHERE tg_user_id = :tg AND is_active"
            ),
            {"tg": tg_id},
        )
        return result.mappings().first()


async def ensure_user(tg_id: int, full_name: str):
    """Create or re-activate a user, linking them to the first farm on record."""
    async with engine.begin() as conn:
        farm_id = (await conn.execute(text("SELECT id FROM farms ORDER BY id LIMIT 1"))).scalar()
        result = await conn.execute(
            text(
                """
                INSERT INTO users (tg_user_id, full_name, farm_id, is_active, role)
                VALUES (:tg, :name, :farm, true, 'admin')
                ON CONFLICT (tg_user_id)
                DO UPDATE SET is_active = true, full_name = EXCLUDED.full_name
                RETURNING id, tg_user_id, full_name, phone, farm_id, role
                """
            ),
            {"tg": tg_id, "name": full_name, "farm": farm_id},
        )
        return result.mappings().first()


async def add_agronomist(tg_id: int, full_name: str | None, farm_id: int | None):
    """Whitelist a new agronomist (or re-activate an existing user) on the
    admin's farm. Never downgrades an existing admin — role is left untouched
    on conflict."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                INSERT INTO users (tg_user_id, full_name, farm_id, is_active, role)
                VALUES (:tg, :name, :farm, true, 'agronomist')
                ON CONFLICT (tg_user_id)
                DO UPDATE SET
                    is_active = true,
                    full_name = COALESCE(EXCLUDED.full_name, users.full_name),
                    farm_id = COALESCE(users.farm_id, EXCLUDED.farm_id)
                RETURNING tg_user_id, full_name, role
                """
            ),
            {"tg": tg_id, "name": full_name, "farm": farm_id},
        )
        return result.mappings().first()


async def deactivate_user(tg_id: int):
    """Revoke a user's access (soft — keeps the row and their submissions).
    Returns the affected user's name/role, or None if no such active user."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE users SET is_active = false "
                "WHERE tg_user_id = :tg AND is_active "
                "RETURNING tg_user_id, full_name, role"
            ),
            {"tg": tg_id},
        )
        return result.mappings().first()


async def set_user_phone(tg_id: int, phone: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET phone = :phone WHERE tg_user_id = :tg"),
            {"phone": phone, "tg": tg_id},
        )


async def get_pilot_fields(farm_id: int | None):
    if not farm_id:
        return []
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, name, crop, area_ha FROM fields "
                "WHERE farm_id = :farm AND is_pilot ORDER BY id"
            ),
            {"farm": farm_id},
        )
        return result.mappings().all()


async def resolve_field_id(field_query: str, farm_id: int | None = None):
    """Resolve a /field query to a field id using the SAME matching as
    field_card_text (exact name, 'Поле <q>', or substring), so the map and the
    text card always refer to the same field. Returns the id or None."""
    q = (field_query or "").strip()
    async with engine.connect() as conn:
        sql = "SELECT id, name FROM fields"
        params = {}
        if farm_id:
            sql += " WHERE farm_id = :f"
            params["f"] = farm_id
        sql += " ORDER BY id"
        cands = (await conn.execute(text(sql), params)).mappings().all()
    field = next(
        (c for c in cands if c["name"] == q or c["name"] == f"Поле {q}"
         or (q and q.lower() in c["name"].lower())),
        None,
    )
    return field["id"] if field else None


async def get_field_polygons(simplify: float = 0.00005):
    """All fields' geometry as GeoJSON (lightly simplified to cut vertex count),
    for drawing outline maps. Skips fields without geometry."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, is_pilot, ST_AsGeoJSON(ST_Simplify(geom, :t)) AS gj "
                "FROM fields WHERE geom IS NOT NULL"
            ),
            {"t": simplify},
        )
        return result.mappings().all()


async def find_fields_by_number(farm_id: int | None, number: str):
    """Resolve a typed field number ('125', '76/108', '31-1') to field rows.
    Fields are named 'Поле <номер> · <группа>' (or 'Поле <номер>' for pilots),
    so we compare the typed value to the number part. Usually one match; can be
    several when the same number exists in more than one field group."""
    if not farm_id or not number:
        return []
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                r"""
                SELECT id, name, crop, area_ha FROM fields
                WHERE farm_id = :farm
                  AND btrim(regexp_replace(
                        split_part(name, ' · ', 1), '^Поле\s+', '')) = :n
                ORDER BY is_pilot DESC, id
                """
            ),
            {"farm": farm_id, "n": number},
        )
        return result.mappings().all()


async def get_pending_submission(user_id: int):
    """Most recent of the user's submissions stuck at awaiting_metadata.

    Used by /finish to resume an interrupted FSM (state in Redis expires
    after 10 min, but the DB row lives forever). Joins fields so the
    resume prompt can show the agronomist which photo we're resuming.
    """
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT s.id, s.category, s.subcategory, s.field_id, s.created_at,
                       COALESCE(f.name, 'вне пилота') AS field_name
                FROM submissions s
                LEFT JOIN fields f ON f.id = s.field_id
                WHERE s.user_id = :user_id AND s.status = 'awaiting_metadata'
                ORDER BY s.created_at DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
        return result.mappings().first()


async def get_recent_treatments(field_id: int, limit: int = 5):
    """Most recent operations on a field that applied a product — the buttons
    the agronomist taps to link a photo to its spray context. Newest first."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT id, product, treatment_date
                FROM field_treatments
                WHERE field_id = :fid
                  AND product IS NOT NULL AND btrim(product) <> ''
                ORDER BY treatment_date DESC NULLS LAST
                LIMIT :lim
                """
            ),
            {"fid": field_id, "lim": limit},
        )
        return result.mappings().all()


async def get_top_species():
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, latin_name, russian_name FROM weed_species "
                "WHERE is_regional_top ORDER BY id"
            )
        )
        return result.mappings().all()


async def get_species(species_id: int):
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, latin_name, russian_name FROM weed_species WHERE id = :id"),
            {"id": species_id},
        )
        return result.mappings().first()


async def create_submission(
    submission_id: str,
    user_id: int,
    field_id: int | None,  # None = off-pilot training photo ("Другое поле")
    image_url: str,
    width: int | None,
    height: int | None,
    image_hash: str | None = None,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO submissions
                    (id, user_id, field_id, image_url, image_width, image_height,
                     image_hash, status)
                VALUES (:id, :user_id, :field_id, :image_url, :w, :h, :hash,
                        'awaiting_metadata')
                """
            ),
            {
                "id": submission_id,
                "user_id": user_id,
                "field_id": field_id,
                "image_url": image_url,
                "w": width,
                "h": height,
                "hash": image_hash,
            },
        )


async def find_duplicate_submission(user_id: int, image_hash: str):
    """Return an existing (non-duplicate) submission by this user with the same
    image bytes, or None. Used to skip byte-identical re-uploads at upload time."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, created_at FROM submissions "
                "WHERE user_id = :u AND image_hash = :h AND status <> 'duplicate' "
                "ORDER BY created_at LIMIT 1"
            ),
            {"u": user_id, "h": image_hash},
        )
        return result.mappings().first()


async def update_submission(submission_id: str, **fields) -> None:
    if not fields:
        return
    allowed = {
        "category",
        "subcategory",
        "comment_text",
        "comment_text_en",         # English (YandexGPT) of the typed note
        "comment_voice_url",
        "comment_voice_text",      # was missing → transcripts were silently dropped
        "comment_voice_text_en",   # English (YandexGPT) of the voice note
        "treatment_id",            # FK → field_treatments (photo ↔ spray link)
        "treatment_note",          # free-text/voice treatment ("Другое")
        "status",
    }
    sets = [f"{key} = :{key}" for key in fields if key in allowed]
    if not sets:
        return
    params = {key: value for key, value in fields.items() if key in allowed}
    params["id"] = submission_id
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"UPDATE submissions SET {', '.join(sets)}, updated_at = NOW() "
                "WHERE id = :id"
            ),
            params,
        )


async def get_user_history(user_id: int, limit: int = 10):
    """Return the user's most recent saved submissions, newest first.

    Joins fields for the readable field name and weed_species so a stored
    latin subcategory can be shown back in Russian.
    """
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT
                    s.created_at,
                    s.category,
                    s.subcategory,
                    s.comment_text,
                    s.comment_voice_url,
                    s.comment_voice_text,
                    COALESCE(f.name, 'вне пилота') AS field_name,
                    -- For keyboard-picked species, subcategory is the Latin
                    -- name and the join gives a Russian display name.
                    -- For free-text ("Другой") rows, subcategory IS the
                    -- typed text and the join misses; fall back to it.
                    COALESCE(ws.russian_name, s.subcategory) AS species_name
                FROM submissions s
                LEFT JOIN fields f ON f.id = s.field_id
                LEFT JOIN weed_species ws ON ws.latin_name = s.subcategory
                WHERE s.user_id = :user_id AND s.status <> 'draft'
                ORDER BY s.created_at DESC
                LIMIT :limit
                """
            ),
            {"user_id": user_id, "limit": limit},
        )
        return result.mappings().all()


async def get_user_stats(user_id: int):
    """Aggregate counts for /stats: today, this week, total, and the number of
    distinct days this week the user uploaded at least one photo (engagement)."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT
                    count(*) FILTER (WHERE created_at::date = CURRENT_DATE) AS today,
                    count(*) FILTER (WHERE created_at >= date_trunc('week', CURRENT_DATE)) AS week,
                    count(*) AS total,
                    count(DISTINCT created_at::date)
                        FILTER (WHERE created_at >= date_trunc('week', CURRENT_DATE)) AS active_days
                FROM submissions
                WHERE user_id = :user_id AND status <> 'draft'
                """
            ),
            {"user_id": user_id},
        )
        return result.mappings().first()


async def delete_submission(submission_id: str):
    """Hard-delete an in-progress submission (used by /cancel). Guarded to
    rows still at status='awaiting_metadata', so a finished/labeled
    submission can never be removed even if called mid-flow. Returns the
    deleted row's image_url (for S3 cleanup), or None if nothing matched."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "DELETE FROM submissions "
                "WHERE id = :id AND status = 'awaiting_metadata' "
                "RETURNING image_url"
            ),
            {"id": submission_id},
        )
        row = result.first()
        return row[0] if row else None


async def count_user_submissions(user_id: int) -> tuple[int, int]:
    """Returns (today, this_week) counts of saved submissions for the user."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT
                    count(*) FILTER (WHERE created_at::date = CURRENT_DATE) AS today,
                    count(*) FILTER (WHERE created_at >= date_trunc('week', CURRENT_DATE)) AS week
                FROM submissions
                WHERE user_id = :user_id AND status <> 'draft'
                """
            ),
            {"user_id": user_id},
        )
        row = result.mappings().first()
        return int(row["today"]), int(row["week"])


async def get_all_recent_submissions(limit: int = 15):
    """Recent saved submissions across ALL users (admin /all view).

    Like get_user_history but global and with the uploader's name + status,
    so the admin can see what every agronomist sent — the per-user /history
    only ever shows the caller's own photos.
    """
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT
                    s.created_at,
                    s.category,
                    s.subcategory,
                    s.status,
                    s.comment_text,
                    s.comment_voice_url,
                    s.comment_voice_text,
                    COALESCE(f.name, 'вне пилота') AS field_name,
                    u.full_name AS uploader,
                    COALESCE(ws.russian_name, s.subcategory) AS species_name
                FROM submissions s
                LEFT JOIN fields f ON f.id = s.field_id
                LEFT JOIN users u ON u.id = s.user_id
                LEFT JOIN weed_species ws ON ws.latin_name = s.subcategory
                WHERE s.status <> 'draft'
                ORDER BY s.created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        return result.mappings().all()


async def get_team_week_counts():
    """Per-user count of saved submissions so far this week (for the /all header)."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT u.full_name, count(*) AS week
                FROM submissions s
                JOIN users u ON u.id = s.user_id
                WHERE s.status <> 'draft'
                  AND s.created_at >= date_trunc('week', CURRENT_DATE)
                GROUP BY u.full_name
                ORDER BY count(*) DESC
                """
            )
        )
        return result.mappings().all()


def _catalog_stem(crop: str | None) -> str:
    t = (crop or "").lower()
    if "пшениц" in t:
        return "пшениц"
    if "подсолнеч" in t:
        return "подсолнеч"
    if "соя" in t or "сои" in t:
        return "соя"
    return t.split()[0] if t else ""


_OPCAT_RU = {"protection": "защита", "fertilizer": "удобрения",
             "tillage": "обработка почвы", "sowing": "сев"}


async def field_card_text(field_query: str, farm_id: int | None = None) -> str:
    """Integrated data-layer card for one field: operations by category, plant-
    protection rotation per season×crop, recent treatments with active substances,
    weather coverage, NDVI trend, and the catalog's candidate-product count for the
    current crop. Shared by the /field bot command and the field_summary CLI.
    farm_id scopes the field lookup (None = any field)."""
    q = (field_query or "").strip()
    async with engine.connect() as conn:
        if farm_id:
            cands = (await conn.execute(text(
                "SELECT id, name, crop, area_ha FROM fields WHERE farm_id=:f ORDER BY id"),
                {"f": farm_id})).mappings().all()
        else:
            cands = (await conn.execute(text(
                "SELECT id, name, crop, area_ha FROM fields ORDER BY id"))).mappings().all()
        field = next((c for c in cands if c["name"] == q or c["name"] == f"Поле {q}"
                      or (q and q.lower() in c["name"].lower())), None)
        if field is None:
            avail = ", ".join(c["name"] for c in cands) or "—"
            return f"Поле не найдено: «{q}».\nДоступные поля: {avail}"
        fid = field["id"]

        cats = (await conn.execute(text(
            "SELECT op_category, count(*) c FROM field_treatments WHERE field_id=:i "
            "GROUP BY op_category ORDER BY c DESC"), {"i": fid})).all()
        span = (await conn.execute(text(
            "SELECT min(season) lo, max(season) hi, count(*) c FROM field_treatments WHERE field_id=:i"),
            {"i": fid})).first()
        rot = (await conn.execute(text(
            "SELECT season, crop, array_agg(DISTINCT product) prods FROM field_treatments "
            "WHERE field_id=:i AND op_category='protection' AND product IS NOT NULL AND product<>'' "
            "GROUP BY season, crop ORDER BY season, crop"), {"i": fid})).all()
        recent = (await conn.execute(text(
            "SELECT treatment_date, product, active_substance FROM field_treatments "
            "WHERE field_id=:i AND op_category='protection' ORDER BY treatment_date DESC LIMIT 5"),
            {"i": fid})).mappings().all()
        w = (await conn.execute(text(
            "SELECT count(*) c, min(date) lo, max(date) hi FROM weather_daily WHERE field_id=:i"),
            {"i": fid})).first()
        ndvi = (await conn.execute(text(
            "SELECT round(ndvi,2) FROM vegetation_weekly WHERE field_id=:i AND ndvi IS NOT NULL "
            "ORDER BY week_start DESC LIMIT 6"), {"i": fid})).scalars().all()
        prot = (await conn.execute(text(
            "SELECT active_substance, season FROM field_treatments WHERE field_id=:i "
            "AND op_category='protection' AND active_substance IS NOT NULL"), {"i": fid})).all()
        # cross-field data for the same-crop NDVI baseline (farm-wide rotation)
        cropc = (await conn.execute(text(
            "SELECT field_id, year, crop FROM field_crops WHERE crop IS NOT NULL"))).all()
        all_ndvi = (await conn.execute(text(
            "SELECT field_id, week_start, week_no, ndvi FROM vegetation_weekly "
            "WHERE ndvi IS NOT NULL"))).all()
        fcrops = (await conn.execute(text(
            "SELECT year, crop, variety, yield_cwt FROM field_crops WHERE field_id=:i "
            "ORDER BY year DESC"), {"i": fid})).all()
        cur = (await conn.execute(text(
            "SELECT crop FROM field_treatments WHERE field_id=:i AND crop IS NOT NULL AND crop<>'' "
            "ORDER BY treatment_date DESC LIMIT 1"), {"i": fid})).scalar()
        stem = _catalog_stem(cur)
        ncat = (await conn.execute(text(
            "SELECT count(*) FROM pesticide_applications WHERE lower(crop) LIKE :s AND status='Действует'"),
            {"s": f"%{stem}%"})).scalar() if stem else 0

    meta = []
    if field["crop"]:
        meta.append(field["crop"])
    if field["area_ha"] is not None:
        meta.append(f"{float(field['area_ha']):g} га")
    lines = [f"📍 {field['name']}" + (f" ({', '.join(meta)})" if meta else ""), ""]
    if span and span.c:
        catstr = ", ".join(f"{_OPCAT_RU.get(c[0], c[0])} {c[1]}" for c in cats)
        lines.append(f"🧪 Операции: {span.c} за {span.lo}–{span.hi} ({catstr})")
        lines.append("\n🔄 Защита по сезонам:")
        for r in rot:
            shown, extra = r[2][:8], ("" if len(r[2]) <= 8 else f" +{len(r[2]) - 8}")
            lines.append(f"  {r[0]} · {r[1] or '—'}: {'; '.join(shown)}{extra}")
        if recent:
            lines.append("\nпоследние обработки (с д.в.):")
            for r in recent:
                dv = f" — {r['active_substance']}" if r["active_substance"] else ""
                lines.append(f"  {r['treatment_date']:%d.%m.%Y} {r['product']}{dv}")
    else:
        lines.append("🧪 История обработок: нет данных")
    if fcrops:
        lines.append("\n🌾 Севооборот (CropWise):")
        for yr, crop, variety, yld in fcrops:
            extra = f" · {variety}" if variety else ""
            if yld:
                extra += f" · {float(yld):g} ц/га"
            lines.append(f"  {yr}: {crop}{extra}")
    if w and w.c:
        lines.append(f"\n☁️ Погода: {w.c} дней ({w.lo:%Y}–{w.hi:%Y})")
    if ndvi:
        lines.append("🌱 NDVI (свежие→старые): " + ", ".join(f"{float(x):g}" for x in ndvi))
    ml = moa_lines([(r[0], r[1]) for r in prot])
    if ml:
        lines.append("\n🧬 Режимы действия (повторы → риск резистентности):")
        lines.extend(ml)
    crop_map = {(f_id, yr): crop for f_id, yr, crop in cropc}
    al, note = ndvi_anomaly_samecrop(fid, crop_map, all_ndvi)
    if al:
        lines.append(f"\n⚠️ NDVI-аномалии ({note}):")
        lines.extend(al)
    elif note.startswith("база"):
        lines.append(f"\n✓ NDVI в пределах нормы ({note})")
    elif note:
        lines.append(f"\nℹ️ NDVI: {note}")
    if ncat:
        lines.append(f"📖 Каталог: ~{ncat} действующих препаратов для культуры «{cur}»")
    return "\n".join(lines)

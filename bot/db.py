import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bot.config import settings
from bot.moa import moa_lines, ndvi_anomalies_all, ndvi_anomaly_samecrop

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


async def get_user_by_email(email: str):
    """Active user whose email matches (case-insensitive), or None. Used by the
    web email-login flow to resolve an address → the user the code belongs to."""
    e = (email or "").strip().lower()
    if not e:
        return None
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, tg_user_id, full_name, phone, farm_id, role "
                "FROM users WHERE lower(email) = :e AND is_active"
            ),
            {"e": e},
        )
        return result.mappings().first()


async def set_user_email(tg_id: int, email: str) -> bool:
    """Attach an email to a user (for email login). Returns False if the address
    is already taken by another user (unique index violation)."""
    e = (email or "").strip().lower()
    try:
        async with engine.begin() as conn:
            res = await conn.execute(
                text("UPDATE users SET email = :e WHERE tg_user_id = :tg AND is_active"),
                {"e": e, "tg": tg_id},
            )
            return res.rowcount > 0
    except Exception:
        return False


async def add_push_subscription(tg_user_id: int, endpoint: str, p256dh: str, auth: str) -> None:
    """Store (or refresh) a Web Push subscription for a device. Keyed on the unique
    endpoint, so re-subscribing the same device just updates its keys/owner."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO push_subscriptions (tg_user_id, endpoint, p256dh, auth)
                VALUES (:tg, :ep, :p, :a)
                ON CONFLICT (endpoint)
                DO UPDATE SET tg_user_id = EXCLUDED.tg_user_id,
                              p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth
                """
            ),
            {"tg": tg_user_id, "ep": endpoint, "p": p256dh, "a": auth},
        )


async def get_push_subscriptions(tg_user_id: int):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE tg_user_id = :tg"),
            {"tg": tg_user_id},
        )
        return rows.mappings().all()


async def delete_push_subscription(endpoint: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM push_subscriptions WHERE endpoint = :ep"), {"ep": endpoint}
        )


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


def _field_number(name: str) -> str:
    """The number part of a field name: 'Поле 47 · Красное' -> '47',
    'Поле 76/108' -> '76/108'."""
    base = (name or "").split(" · ", 1)[0]
    return re.sub(r"^Поле\s+", "", base).strip()


def _pick_field(cands, q):
    """Pick ONE field for a typed query, exact-first so a number never matches a
    longer one ('47' must not return 'Поле 147'). Tiers: full-name exact → number-
    part exact → loose substring (DISABLED for a purely numeric query — that is the
    boundary that caused the 47→147 bug). cands are dict-likes with a 'name'."""
    q = (q or "").strip()
    if not q:
        return None
    ql = q.lower()
    qnum = re.sub(r"^поле\s+", "", ql).strip()        # 'поле 47' behaves like '47'
    for c in cands:                                   # 1. exact full name / 'Поле <q>'
        nl = c["name"].lower()
        if nl == ql or nl == f"поле {ql}":
            return c
    for c in cands:                                   # 2. exact number part ('47' == '47')
        if _field_number(c["name"]).lower() == qnum:
            return c
    if re.fullmatch(r"\d+", qnum):                    # numeric query: no substring fallback
        return None
    for c in cands:                                   # 3. loose substring (group names etc.)
        if qnum and qnum in c["name"].lower():
            return c
    return None


async def resolve_field_id(field_query: str, farm_id: int | None = None):
    """Resolve a /field query to a field id using the SAME matching as
    field_card_text (exact name, 'Поле <q>', or number/substring), so the map and the
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
    field = _pick_field(cands, q)
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


async def field_at_point(lat: float, lon: float, farm_id: int | None = None):
    """The field whose polygon contains a GPS point ('это поле' by geolocation).
    Returns the field row or None."""
    async with engine.connect() as conn:
        sql = ("SELECT id, name, crop, area_ha FROM fields WHERE geom IS NOT NULL "
               "AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))")
        params = {"lon": lon, "lat": lat}
        if farm_id:
            sql += " AND farm_id = :f"
            params["f"] = farm_id
        return (await conn.execute(text(sql + " LIMIT 1"), params)).mappings().first()


async def find_fields_by_number(farm_id: int | None, number: str):
    """Resolve a typed field number ('125', '76/108', '31-1') to field rows.
    Fields are named 'Поле <номер> · <группа>' (or 'Поле <номер>' for pilots),
    so we compare the typed value to the number part. Usually one match; can be
    several when the same number exists in more than one field group.

    Agronomists often write '<номер>/<площадь, га>' (e.g. '124/92' = поле 124, 92 га) to
    disambiguate, so if the full value doesn't match, retry on the field-number part before
    the '/'. Real slash-named fields ('Поле 121/140') match the full value first, unaffected."""
    if not farm_id or not number:
        return []
    number = re.sub(r"\s*/\s*", "/", number.strip())          # «124 / 92» → «124/92»
    sql = text(
        r"""
        SELECT id, name, crop, area_ha FROM fields
        WHERE farm_id = :farm
          AND btrim(regexp_replace(
                split_part(name, ' · ', 1), '^Поле\s+', '')) = :n
        ORDER BY is_pilot DESC, id
        """
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(sql, {"farm": farm_id, "n": number})).mappings().all()
        if not rows and "/" in number:                        # «124/92» → field 124 (after / is га)
            rows = (await conn.execute(
                sql, {"farm": farm_id, "n": number.split("/", 1)[0]})).mappings().all()
        return rows


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


def _norm_crop(c):
    """Canonicalize crop labels so pooling isn't split (e.g. 'Пшеница озимая' and
    'Озимая пшеница' → one label; winter vs spring wheat kept separate — they
    have different phenology)."""
    c = (c or "").strip()
    low = c.lower()
    if "пшениц" in low and "озим" in low:
        return "Озимая пшеница"
    if "пшениц" in low and ("яров" in low or "весн" in low):
        return "Яровая пшеница"
    return c


async def _crop_sow_maps(conn):
    """Build {(field_id, year): crop} and {(field_id, year): sow_date} for the
    phenology (days-after-sowing) baseline. field_treatments gives crop + the
    actual sowing-op date per season (2021-26); field_crops (2025-27) overlays as
    the authoritative source (and correctly pairs winter crops with their autumn
    sow date)."""
    crop_map, sow_map = {}, {}
    for fid, season, crop in (await conn.execute(text(
        "SELECT field_id, season, mode() WITHIN GROUP (ORDER BY crop) FROM field_treatments "
        "WHERE crop IS NOT NULL AND crop <> '' AND season IS NOT NULL "
        "GROUP BY field_id, season"))).all():
        crop_map[(fid, season)] = _norm_crop(crop)
    for fid, season, sow in (await conn.execute(text(
        "SELECT field_id, season, min(treatment_date) FROM field_treatments "
        "WHERE op_category = 'sowing' AND treatment_date IS NOT NULL AND season IS NOT NULL "
        "GROUP BY field_id, season"))).all():
        sow_map[(fid, season)] = sow
    for fid, yr, crop, sow in (await conn.execute(text(
        "SELECT field_id, year, crop, sow_date FROM field_crops"))).all():
        if crop:
            crop_map[(fid, yr)] = _norm_crop(crop)
        if sow:
            sow_map[(fid, yr)] = sow
    return crop_map, sow_map


async def ndvi_scan(farm_id: int | None = None):
    """Proactive NDVI check across ALL farm fields (not just pilots). Uses the
    batch same-crop anomaly engine (one pooled baseline) so scanning ~300 fields
    stays fast. Returns (as_of_week, results) where results = [{name, crop, lines,
    note}] for fields we could actually evaluate (have current-season NDVI + a
    same-crop baseline); `lines` is non-empty only for anomalies."""
    async with engine.connect() as conn:
        sql = "SELECT id, name, crop FROM fields"
        params = {}
        if farm_id:
            sql += " WHERE farm_id = :f"
            params["f"] = farm_id
        sql += " ORDER BY id"
        fields = (await conn.execute(text(sql), params)).mappings().all()
        crop_map, sow_map = await _crop_sow_maps(conn)
        all_ndvi = (await conn.execute(text(
            "SELECT field_id, week_start, week_no, ndvi, source FROM vegetation_weekly "
            "WHERE ndvi IS NOT NULL"))).all()
        as_of = (await conn.execute(text(
            "SELECT max(week_start) FROM vegetation_weekly"))).scalar()
    anomalies = ndvi_anomalies_all([f["id"] for f in fields], crop_map, sow_map, all_ndvi)
    results = []
    for f in fields:
        res = anomalies.get(f["id"])
        if not res:
            continue
        lines, note = res
        if note.startswith("база"):   # evaluated (has a same-crop baseline)
            results.append({"name": f["name"], "crop": f["crop"],
                            "lines": lines, "note": note})
    return as_of, results


async def resolve_field(field_query: str, farm_id: int | None = None):
    """Resolve a field query to its full row (id, name, crop, area_ha) using the
    same matching as field_card_text. Returns the mapping or None."""
    fid = await resolve_field_id(field_query, farm_id)
    if fid is None:
        return None
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT id, name, crop, area_ha FROM fields WHERE id = :i"),
            {"i": fid})).mappings().first()


def _norm_product(p: str) -> str:
    s = (p or "").lower().replace("ё", "е")
    s = re.sub(r"\(.*?\)", "", s)      # drop (900 г/л) / (архив)
    return s.split(",")[0].strip()     # drop ", ВРК" etc.


async def lookup_active_substance(product: str):
    """Best-effort active substance (д.в.) for a trade name, from the Госкаталог.
    Picks the most common active_substances for products whose name contains the
    normalized core. None if no match (adjuvant/biostimulant/typo)."""
    core = _norm_product(product)
    if not core:
        return None
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT active_substances FROM pesticide_applications "
            "WHERE active_substances IS NOT NULL AND lower(product_name) LIKE :pat "
            "GROUP BY active_substances ORDER BY count(*) DESC LIMIT 1"),
            {"pat": f"%{core}%"})).scalar()


async def get_registered_products(crop: str, target: str | None = None, limit: int = 30):
    """Products from the Госкаталог registry registered for a crop (and target),
    so the chat assistant recommends only real, registered options."""
    async with engine.connect() as conn:
        sql = ("SELECT DISTINCT product_name, active_substances, target, rate, registrant "
               "FROM pesticide_applications WHERE crop ILIKE :crop")
        params = {"crop": f"%{crop}%"}
        if target:
            sql += " AND target ILIKE :target"
            params["target"] = f"%{target}%"
        sql += " ORDER BY product_name LIMIT :lim"
        params["lim"] = limit
        return (await conn.execute(text(sql), params)).mappings().all()


# Major producers → short label, matched against the Госкаталог `registrant` field (which
# is the OFFICIAL, authoritative source — not the producers' copyrighted atlases). Founder
# decision 2026-06-19, LICENSING.md §2.4. Verified against producer sites: ВЗСП is Август's
# plant (a филиал); «Дюпон Наука и Технологии» is DuPont's RU registrant → Corteva.
# Substrings are matched after lowercasing + ё→е, longest-intent first.
_PRODUCERS = (
    ("Syngenta", ("синген", "syngenta")),
    ("Bayer", ("байер", "bayer")),
    ("BASF", ("басф", "basf")),
    ("Corteva", ("кортева", "corteva", "дюпон", "dupont")),
    ("FMC", ("эфэмси", "фмс кемикал", "fmc")),
    ("Adama", ("адама", "adama")),
    ("Август", ("август", "взсп")),
    ("Щёлково Агрохим", ("щелков",)),
)


def producer_label(registrant: str | None) -> str | None:
    """Short producer label for a Госкаталог registrant string, or None if not a tracked
    major producer (generic/other registrants stay untagged)."""
    s = (registrant or "").lower().replace("ё", "е")
    for label, subs in _PRODUCERS:
        if any(sub in s for sub in subs):
            return label
    return None


async def search_literature(query: str, limit: int = 3):
    """Top open-access (CC BY) agronomy articles matching a question, by Russian full-text
    rank over title+abstract. OR-matches significant words (≥4 chars) so a verbose question
    still retrieves on its key terms. Used to ground the chat assistant with citable science."""
    terms = re.findall(r"[а-яёa-z0-9]{4,}", (query or "").lower())
    if not terms:
        return []
    tsq = " | ".join(terms[:12])
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT title, authors, journal, year, url, abstract, license, "
            "ts_rank(to_tsvector('russian', coalesce(title,'')||' '||coalesce(abstract,'')), "
            "        to_tsquery('russian', :q)) AS rank "
            "FROM agro_literature "
            "WHERE to_tsvector('russian', coalesce(title,'')||' '||coalesce(abstract,'')) "
            "      @@ to_tsquery('russian', :q) "
            "ORDER BY rank DESC LIMIT :lim"),
            {"q": tsq, "lim": limit})).mappings().all()


async def find_similar_treatment(field_id, treatment_date, op_category, product):
    """Existing op(s) on the same field + date + category with the same product —
    used to warn an agronomist about a likely duplicate (e.g. a colleague already
    logged it) before saving. Only meaningful when a product is named."""
    if not (field_id and treatment_date and product):
        return []
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT operation, product, dose, operator, source FROM field_treatments "
            "WHERE field_id=:fid AND treatment_date=:td AND op_category=:oc "
            "AND lower(coalesce(product,''))=lower(:pr) ORDER BY id LIMIT 3"),
            {"fid": field_id, "td": treatment_date, "oc": op_category, "pr": product},
        )).mappings().all()


async def insert_bot_treatment(*, field_id, field_name, treatment_date, crop, operation,
                               op_category, product, active_substance, target, dose,
                               area_ha, operator):
    """Insert one agronomist-logged operation (source='bot'). Idempotent via the
    natural-key index (migration 0018). Returns the new row id (truthy) on insert,
    or None if it was an exact duplicate (ON CONFLICT DO NOTHING) — so the caller
    only pushes a FRESH row to CropWise and can mark it synced by id."""
    season = treatment_date.year if treatment_date else None
    async with engine.begin() as conn:
        res = await conn.execute(text(
            "INSERT INTO field_treatments (field_id, field_name, treatment_date, season, "
            "crop, operation, op_category, product, active_substance, target, dose, "
            "area_ha, operator, source) VALUES "
            "(:fid,:fn,:td,:se,:cr,:op,:oc,:pr,:asb,:tg,:do,:ar,:opr,'bot') "
            "ON CONFLICT (field_name, treatment_date, operation, product, dose, area_ha) "
            "DO NOTHING RETURNING id"),
            {"fid": field_id, "fn": field_name, "td": treatment_date, "se": season,
             "cr": crop, "op": operation, "oc": op_category, "pr": product,
             "asb": active_substance, "tg": target, "do": dose, "ar": area_ha,
             "opr": operator})
        return res.scalar()


async def mark_treatment_synced(treatment_id: int) -> None:
    """Stamp a field_treatments row as successfully pushed to CropWise."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE field_treatments SET cropwise_synced_at = NOW() WHERE id = :i"),
            {"i": treatment_id})


async def get_unsynced_bot_treatments(limit: int = 20):
    """Bot-logged operations whose CropWise push never confirmed (synced_at IS NULL).
    Scoped to rows created since the sync flag existed (migration 0025, 2026-06-17)
    so the historical CropWise-imported backlog isn't reported as unsynced."""
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT id, field_name, treatment_date, operation, product, dose "
            "FROM field_treatments "
            "WHERE source = 'bot' AND cropwise_synced_at IS NULL "
            "AND created_at >= '2026-06-17' "
            "ORDER BY created_at DESC LIMIT :lim"),
            {"lim": limit})).mappings().all()


async def get_active_users():
    """Active whitelisted users (for the daily operation-logging nudge)."""
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT tg_user_id, full_name FROM users WHERE is_active"))).mappings().all()


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


async def get_all_species():
    """All weed species (russian + latin) — grounding for the photo-suggestion LLM."""
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT russian_name, latin_name FROM weed_species ORDER BY russian_name"
        ))).mappings().all()


async def get_submission_image_url(submission_id):
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT image_url FROM submissions WHERE id = :i"), {"i": submission_id})).scalar()


async def get_annotators():
    """Telegram ids of active annotators — recipients of the labeling reference sheet."""
    async with engine.connect() as conn:
        return [r[0] for r in (await conn.execute(text(
            "SELECT tg_user_id FROM users WHERE role = 'annotator' AND is_active"))).all()]


async def get_chief_agronomists(farm_id):
    """Active chief agronomists (reviewers) of a farm — who junior submissions go to.
    Build the farm filter conditionally: asyncpg can't type a param used only in
    `:f IS NULL`, which threw AmbiguousParameterError and silently broke review delivery."""
    sql = "SELECT tg_user_id, full_name FROM users WHERE role = 'chief_agronomist' AND is_active"
    params = {}
    if farm_id is not None:
        sql += " AND farm_id = :f"
        params["f"] = farm_id
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).mappings().all()


async def get_submission_review(submission_id):
    """Full attributes + submitter (for the CA review card / correction notices)."""
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT s.id, s.category, s.subcategory, s.comment_text, s.comment_voice_text, "
            "s.image_url, s.status, f.name AS field_name, "
            "u.full_name AS submitter, u.tg_user_id AS submitter_tg "
            "FROM submissions s LEFT JOIN fields f ON f.id = s.field_id "
            "LEFT JOIN users u ON u.id = s.user_id WHERE s.id = :i"),
            {"i": submission_id})).mappings().first()


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
        "field_id",                # CA review can re-assign the field
        "status",
        "gps_lat",                 # EXIF GPS from web uploads (Telegram strips it)
        "gps_lon",
        "gps_source",
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
                    count(*) FILTER (WHERE status = 'labeled') AS labeled,
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


async def set_product_price(name: str, price: float, unit: str, note: str | None = None) -> None:
    """Upsert a product's unit price (₽ per л or кг). Founder-supplied — never invented."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO product_prices (product_name, price, unit, note) "
            "VALUES (:n, :p, :u, :note) "
            "ON CONFLICT (product_name) DO UPDATE SET "
            "price = EXCLUDED.price, unit = EXCLUDED.unit, note = EXCLUDED.note, updated_at = now()"),
            {"n": name.strip(), "p": price, "u": unit, "note": note})


async def get_product_prices() -> dict:
    """All prices keyed by lowercased product name → {price, unit}."""
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT product_name, price, unit FROM product_prices"))).mappings().all()
        return {r["product_name"].strip().lower(): {"price": float(r["price"]), "unit": r["unit"]}
                for r in rows}


async def get_protection_products(farm_id: int | None = None):
    """Distinct products used in protection history (so we know what needs pricing).
    Farm-scoped when farm_id is given."""
    async with engine.connect() as conn:
        if farm_id:
            return (await conn.execute(text(
                "SELECT DISTINCT ft.product FROM field_treatments ft JOIN fields f ON f.id = ft.field_id "
                "WHERE f.farm_id = :fm AND ft.op_category = 'protection' "
                "  AND ft.product IS NOT NULL AND ft.product <> '' ORDER BY ft.product"),
                {"fm": farm_id})).scalars().all()
        return (await conn.execute(text(
            "SELECT DISTINCT product FROM field_treatments WHERE op_category = 'protection' "
            "AND product IS NOT NULL AND product <> '' ORDER BY product"))).scalars().all()


async def get_field_protection_baseline(field_id: int):
    """This-season blanket protection passes on a field — the baseline the plan's savings
    are measured against (real CropWise records: product, dose, treated area, target, date).
    Returns (season, [rows])."""
    async with engine.connect() as conn:
        season = (await conn.execute(text(
            "SELECT max(season) FROM field_treatments WHERE field_id = :i"), {"i": field_id})).scalar()
        if season is None:
            return None, []
        rows = (await conn.execute(text(
            "SELECT treatment_date, product, dose, area_ha, target, cost "
            "FROM field_treatments "
            "WHERE field_id = :i AND op_category = 'protection' AND season = :s "
            "  AND product IS NOT NULL AND product <> '' "
            "ORDER BY treatment_date"), {"i": field_id, "s": season})).mappings().all()
        return season, rows


async def get_field_observations(field_id: int, limit: int = 20):
    """Recent scouting on a field — what agronomists saw (category, species, where, when).
    The perception signal the field-plan generator reasons over. GPS, when present, lets
    it talk about zones instead of the whole field."""
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            """
            SELECT created_at, category, subcategory, comment_text, comment_voice_text,
                   gps_lat, gps_lon
            FROM submissions
            WHERE field_id = :fid AND status NOT IN ('draft','rejected','duplicate')
            ORDER BY created_at DESC
            LIMIT :lim
            """), {"fid": field_id, "lim": limit})
        return rows.mappings().all()


async def get_team_progress():
    """Team-wide totals for the collective goal: photos collected toward the model
    (everything not draft/rejected/duplicate) and how many reached training (labeled)."""
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT count(*) FILTER (WHERE status NOT IN ('draft','rejected','duplicate')) AS collected, "
            "       count(*) FILTER (WHERE status = 'labeled') AS trained "
            "FROM submissions"
        ))).mappings().first()
        return int(row["collected"]), int(row["trained"])


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
        field = _pick_field(cands, q)
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
            "GROUP BY season, crop ORDER BY season DESC, crop"), {"i": fid})).all()
        recent = (await conn.execute(text(
            "SELECT treatment_date, product, active_substance FROM field_treatments "
            "WHERE field_id=:i AND op_category='protection' ORDER BY treatment_date DESC LIMIT 5"),
            {"i": fid})).mappings().all()
        # Seed (latest sowing op) + fertilizer history — same shape as protection.
        seed = (await conn.execute(text(
            "SELECT season, crop, product FROM field_treatments WHERE field_id=:i "
            "AND op_category='sowing' AND product IS NOT NULL AND product<>'' "
            "ORDER BY treatment_date DESC LIMIT 1"), {"i": fid})).first()
        fert_rot = (await conn.execute(text(
            "SELECT season, crop, array_agg(DISTINCT product) prods FROM field_treatments "
            "WHERE field_id=:i AND op_category='fertilizer' AND product IS NOT NULL AND product<>'' "
            "GROUP BY season, crop ORDER BY season DESC, crop"), {"i": fid})).all()
        fert_recent = (await conn.execute(text(
            "SELECT treatment_date, product FROM field_treatments WHERE field_id=:i "
            "AND op_category='fertilizer' AND product IS NOT NULL AND product<>'' "
            "ORDER BY treatment_date DESC LIMIT 5"), {"i": fid})).mappings().all()
        # Weather is regional — the same Valujki station / meteoblue series for
        # the whole farm (fields share the area), loaded once against the pilots.
        # Show it for ANY field by reading the distinct-day series, not per field_id.
        w = (await conn.execute(text(
            "SELECT count(DISTINCT date) c, min(date) lo, max(date) hi FROM weather_daily"))).first()
        ndvi = (await conn.execute(text(
            "SELECT round(ndvi,2) FROM vegetation_weekly WHERE field_id=:i AND ndvi IS NOT NULL "
            "ORDER BY week_start DESC LIMIT 6"), {"i": fid})).scalars().all()
        prot = (await conn.execute(text(
            "SELECT active_substance, season FROM field_treatments WHERE field_id=:i "
            "AND op_category='protection' AND active_substance IS NOT NULL"), {"i": fid})).all()
        # cross-field data for the same-crop, same-phase NDVI baseline
        crop_map, sow_map = await _crop_sow_maps(conn)
        all_ndvi = (await conn.execute(text(
            "SELECT field_id, week_start, week_no, ndvi, source FROM vegetation_weekly "
            "WHERE ndvi IS NOT NULL"))).all()
        fcrops = (await conn.execute(text(
            "SELECT year, crop, variety, yield_cwt FROM field_crops WHERE field_id=:i "
            "ORDER BY year DESC"), {"i": fid})).all()
        # Per-season crop from the treatments (field_crops only covers 2025-26),
        # so the rotation can span the full 5 years of history.
        rotation = (await conn.execute(text(
            "SELECT season, mode() WITHIN GROUP (ORDER BY crop) AS crop FROM field_treatments "
            "WHERE field_id=:i AND season IS NOT NULL AND crop IS NOT NULL AND crop<>'' "
            "GROUP BY season ORDER BY season DESC"), {"i": fid})).all()
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
    lines = [f"📍 {field['name']}" + (f" ({', '.join(meta)})" if meta else "")]

    # (2) Севооборот — last 5 years, treatment seasons enriched with
    # field_crops variety/yield (field_crops alone only covers 2025-26).
    fc = {yr: (crop, variety, yld) for yr, crop, variety, yld in fcrops}
    tr = {season: crop for season, crop in rotation}
    years = sorted(set(fc) | set(tr), reverse=True)[:5]
    if years:
        lines.append("\n🌾 Севооборот (CropWise):")
        for yr in years:
            crop, variety, yld = fc.get(yr, (tr.get(yr), None, None))
            extra = f" · {variety}" if variety else ""
            if yld:
                extra += f" · {float(yld):g} ц/га"
            lines.append(f"  {yr}: {crop or '—'}{extra}")

    # (3) Семена
    if seed:
        lines.append(f"\n🫘 Семена ({seed[0]} · {seed[1] or '—'}): {seed[2]}")

    # (4) Удобрения по сезонам
    if fert_rot:
        lines.append("\n🧴 Удобрения по сезонам:")
        for r in fert_rot:
            shown, extra = r[2][:8], ("" if len(r[2]) <= 8 else f" +{len(r[2]) - 8}")
            lines.append(f"  {r[0]} · {r[1] or '—'}: {'; '.join(shown)}{extra}")
        if fert_recent:
            lines.append("\nпоследние внесения:")
            for r in fert_recent:
                lines.append(f"  {r['treatment_date']:%d.%m.%Y} {r['product']}")

    # (5) Защита по сезонам
    if rot:
        lines.append("\n🔄 Защита по сезонам:")
        for r in rot:
            shown, extra = r[2][:8], ("" if len(r[2]) <= 8 else f" +{len(r[2]) - 8}")
            lines.append(f"  {r[0]} · {r[1] or '—'}: {'; '.join(shown)}{extra}")
        if recent:
            lines.append("\nпоследние обработки (с д.в.):")
            for r in recent:
                dv = f" — {r['active_substance']}" if r["active_substance"] else ""
                lines.append(f"  {r['treatment_date']:%d.%m.%Y} {r['product']}{dv}")

    # (6) Режимы действия (резистентность)
    ml = moa_lines([(r[0], r[1]) for r in prot])
    if ml:
        lines.append("\n🧬 Режимы действия (повторы → риск резистентности):")
        lines.extend(ml)

    # (7) remaining bits
    if span and span.c:
        catstr = ", ".join(f"{_OPCAT_RU.get(c[0], c[0])} {c[1]}" for c in cats)
        lines.append(f"\n🧪 Операции: {span.c} за {span.lo}–{span.hi} ({catstr})")
    else:
        lines.append("\n🧪 История обработок: нет данных")
    if w and w.c:
        lines.append(f"\n☁️ Погода (регион): {w.c} дней ({w.lo:%Y}–{w.hi:%Y})")
    if ndvi:
        lines.append("🌱 NDVI (свежие→старые): " + ", ".join(f"{float(x):g}" for x in ndvi))
    al, note = ndvi_anomaly_samecrop(fid, crop_map, sow_map, all_ndvi)
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

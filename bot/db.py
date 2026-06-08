from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bot.config import settings

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
                SELECT s.id, s.category, s.subcategory, s.created_at,
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
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO submissions
                    (id, user_id, field_id, image_url, image_width, image_height, status)
                VALUES (:id, :user_id, :field_id, :image_url, :w, :h, 'awaiting_metadata')
                """
            ),
            {
                "id": submission_id,
                "user_id": user_id,
                "field_id": field_id,
                "image_url": image_url,
                "w": width,
                "h": height,
            },
        )


async def update_submission(submission_id: str, **fields) -> None:
    if not fields:
        return
    allowed = {
        "category",
        "subcategory",
        "comment_text",
        "comment_voice_url",
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

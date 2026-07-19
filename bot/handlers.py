import asyncio
import hashlib
import logging
import re
import secrets
from datetime import date, datetime, timedelta
from uuid import uuid4

import redis.asyncio as aioredis
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from bot.config import settings
from bot.db import (
    add_agronomist,
    count_user_submissions,
    create_submission,
    create_wall_from_submission,
    deactivate_user,
    delete_submission,
    field_card_text,
    field_at_point,
    find_duplicate_submission,
    find_fields_by_number,
    get_all_recent_submissions,
    get_all_species,
    get_chief_agronomists,
    get_pending_submission,
    get_submission_image_url,
    get_submission_review,
    get_field_polygons,
    get_demo_field_list,
    get_pilot_fields,
    get_recent_treatments,
    get_species,
    resolve_field_id,
    get_team_week_counts,
    get_top_species,
    find_similar_treatment,
    get_user_history,
    annotate_latest_plan_run,
    get_plan_runs,
    get_product_prices,
    get_protection_products,
    get_team_progress,
    get_user_stats,
    set_product_price,
    get_unsynced_bot_treatments,
    insert_bot_treatment,
    lookup_active_substance,
    mark_treatment_synced,
    ndvi_scan,
    resolve_field,
    set_user_email,
    set_user_phone,
    update_submission,
)
from bot import fieldmap
from bot.ndvi_watch import format_digest
from bot.oplog_match import is_fieldless_op, looks_like_oplog
from bot.parse_op import parse_operation, parse_operations
from bot.push import send_push
from bot.cvat_admin import add_label as add_cvat_label
from bot.review_actions import approved_status, notify_submitter_decision
from bot.field_plan import generate_field_plan
from bot.states import CAReport, CAReview, OpLogForm, PhotoForm, ProblemForm
from bot.storage import delete_object, download_bytes, upload_bytes
from bot.weed_suggest import suggest_species
from bot.agro_chat import answer as agro_answer
from bot.transcribe import transcribe
from bot.translate_llm import translate_ru_to_en
from bot.taxonomy import DISEASES, DISEASE_RU_BY_CODE, PESTS_PICKER, PEST_RU_BY_CODE

router = Router()
logger = logging.getLogger("bot.handlers")


async def _ack(callback: CallbackQuery, text: str | None = None) -> None:
    """Acknowledge a callback, but never let it abort the handler. Through the
    Telegram relay an update can arrive late and the callback go stale; a raw
    `callback.answer()` would then throw and we'd lose the user's tap (the
    field/category/species selection). Swallowing it keeps the actual DB write
    running — the next prompt is a fresh message and reaches the user anyway."""
    try:
        await callback.answer(text) if text else await callback.answer()
    except Exception:
        logger.debug("callback.answer() failed (stale query) — continuing")

CATEGORIES = [
    ("Сорняк", "weed"),
    ("Болезнь", "disease"),
    ("Вредитель", "pest"),
    ("Стресс", "stress"),
    ("Контроль", "control"),
    ("Результат обработки", "treatment_result"),
    ("🔍 Обследование поля", "scouting"),   # Pilot v2: field-state pass (no species, no review)
]

CATEGORY_LABELS = {code: label for label, code in CATEGORIES}

# Human-readable submission statuses for the admin /all view, so it's clear
# where each photo is in the pipeline (e.g. already pushed to CVAT).
STATUS_RU = {
    "awaiting_metadata": "не завершено",
    "pending_review": "на проверке у старшего агронома",
    "ready_for_labeling": "ждёт разметки",
    "in_labeling": "в CVAT",
    "labeled": "размечено",
    "stored": "сохранено (разметка не нужна)",
    "needs_species": "ждёт добавления вида в словарь",
    "in_dataset": "в датасете",
}

# Photos sent via Telegram's "Photo" button are always JPEG. Photos sent as
# "File" (paperclip → File) preserve the original MIME (HEIC from iPhone,
# JPEG/PNG from Android, WebP from some apps). Used to pick the S3 object's
# extension + Content-Type so the file is stored as it came.
_MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/jpg":  "jpg",   # non-standard but seen in the wild
    "image/png":  "png",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/webp": "webp",
    "image/gif":  "gif",
}


def _ext_for_mime(mime: str) -> str:
    return _MIME_TO_EXT.get(mime, "bin")


# ---------- keyboards ----------

def _fields_kb(fields) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f["name"] + (f" — {f['crop']}" if f["crop"] else ""),
            callback_data=f"field:{f['id']}")]
        for f in fields
    ]
    # All farm fields are open now; the quick buttons are just the 12 demonstration
    # fields. «Другое поле» lets the agronomist tag any of the rest by typing its number.
    rows.append([InlineKeyboardButton(text="Другое поле (по номеру)", callback_data="field:other")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _category_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f"cat:{code}")] for label, code in CATEGORIES]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _species_kb(species) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=s["russian_name"], callback_data=f"sub:{s['id']}")]
        for s in species
    ]
    rows.append([InlineKeyboardButton(text="Другой", callback_data="sub:other")])
    rows.append([InlineKeyboardButton(text="Пропустить", callback_data="sub:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _disease_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=ru, callback_data=f"dis:{code}")]
        for code, ru in DISEASES
    ]
    rows.append([InlineKeyboardButton(text="Другая болезнь", callback_data="dis:other")])
    rows.append([InlineKeyboardButton(text="Пропустить", callback_data="dis:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _pest_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=ru, callback_data=f"pst:{code}")]
        for code, ru in PESTS_PICKER
    ]
    rows.append([InlineKeyboardButton(text="Другой вредитель", callback_data="pst:other")])
    rows.append([InlineKeyboardButton(text="Пропустить", callback_data="pst:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- onboarding ----------

async def _show_fields(message: Message, farm_id: int | None) -> None:
    fields = await get_demo_field_list(farm_id)
    if not fields:
        await message.answer(
            "Поля ещё не настроены. Их добавит администратор на следующем шаге."
        )
        return

    lines = ["🎯 Ваши контрольные поля (обследуйте их регулярно):"]
    for f in fields:
        meta_parts = []
        if f["crop"]:
            meta_parts.append(f["crop"])
        if f["area_ha"] is not None:
            meta_parts.append(f"{float(f['area_ha']):g} га")
        meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
        lines.append(f"• {f['name']}{meta}")
    lines.append("\nМожно работать с любым полем — при загрузке фото выберите «Другое поле» "
                 "и введите его номер. Готовы начать? Просто отправляйте фото.")
    await message.answer("\n".join(lines))


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user) -> None:
    await state.clear()
    name = user["full_name"] or "коллега"
    await message.answer(f"Здравствуйте, {name}! Я бот NewGrain.")

    if not user["phone"]:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Поделиться номером", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await message.answer("Подтвердите ваш номер телефона:", reply_markup=keyboard)
    else:
        await _show_fields(message, user["farm_id"])


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Abort the current photo upload. If a field was already picked, the
    photo + draft row exist in storage/DB — delete both so a wrong-field
    (or any aborted) upload leaves no trace and never reaches labeling."""
    if await state.get_state() is None:
        await message.answer("Нечего отменять — активной загрузки нет.")
        return

    data = await state.get_data()
    submission_id = data.get("submission_id")
    await state.clear()

    if not submission_id:
        # Cancelled before picking a field — nothing was saved yet.
        await message.answer("Загрузка отменена.", reply_markup=ReplyKeyboardRemove())
        return

    image_url = await delete_submission(submission_id)
    if image_url:
        try:
            key = image_url.split(f"{settings.s3_bucket}/", 1)[-1]
            await delete_object(key)
        except Exception:
            logger.exception("cancel: failed to delete S3 object for %s", submission_id)

    await message.answer(
        "Загрузка отменена — фото удалено. Можете прислать снимок заново.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(Command("history"))
async def cmd_history(message: Message, user) -> None:
    rows = await get_user_history(user["id"])
    if not rows:
        await message.answer("Пока нет сохранённых фото. Отправьте первое — просто пришлите снимок.")
        return

    lines = ["Последние снимки:"]
    for r in rows:
        when = f"{r['created_at']:%d.%m %H:%M}"
        label = CATEGORY_LABELS.get(r["category"], r["category"] or "—")
        parts = [when, r["field_name"] or "поле?", label]
        if r["species_name"]:
            parts.append(r["species_name"])
        line = " · ".join(parts)

        comment = r["comment_text"]
        if comment:
            snippet = comment if len(comment) <= 40 else comment[:39] + "…"
            line += f"\n  💬 {snippet}"
        elif r["comment_voice_text"]:
            voice = r["comment_voice_text"]
            snippet = voice if len(voice) <= 40 else voice[:39] + "…"
            line += f"\n  🎤 {snippet}"
        elif r["comment_voice_url"]:
            line += "\n  🎤 голосовой комментарий"
        lines.append(f"• {line}")

    await message.answer("\n".join(lines))


HELP_TEXT = (
    "Что я умею:\n"
    "📷 Просто пришлите фото — я задам пару уточнений и сохраню снимок.\n\n"
    "Команды:\n"
    "/history — последние сохранённые снимки\n"
    "/stats — сколько фото за сегодня, неделю и всего\n"
    "/fields — ваши пилотные поля\n"
    "/field <поле> — сводка по полю (обработки, погода, NDVI)\n"
    "/scan — проверка полей по NDVI (что требует внимания)\n"
    "/log — записать обработку (голосом или текстом)\n"
    "/export <поле> — выгрузить операции по полю (Excel)\n"
    "/all — последние загрузки всех агрономов\n"
    "/finish — закончить незавершённое фото\n"
    "/problem — сообщить о проблеме или задать вопрос\n"
    "/cancel — отменить текущий шаг\n"
    "/help — это сообщение\n\n"
    "Можно не набирать «/» — просто напишите слово: "
    "история, статистика, поля, помощь. "
    "Для сводки по полю — «поле 76/108»."
)

ADMIN_HELP = (
    "\n\nКоманды администратора:\n"
    "/adduser <id> <имя> — добавить агронома\n"
    "/removeuser <id> — убрать доступ"
)


@router.message(Command("help"))
async def cmd_help(message: Message, user) -> None:
    await message.answer(HELP_TEXT + (ADMIN_HELP if _is_admin(user) else ""))


@router.message(Command("fields"))
async def cmd_fields(message: Message, user) -> None:
    await _show_fields(message, user["farm_id"])


_web_redis = aioredis.from_url(settings.redis_url, decode_responses=True)


async def _scout_mode_on(tg_id: int) -> bool:
    """Whether the agronomist has a scouting session active (photos auto-tag as scouting)."""
    try:
        return bool(await _web_redis.get(f"flagleaf:scoutmode:{tg_id}"))
    except Exception:
        return False


@router.message(Command("scout"))
async def cmd_scout(message: Message, user) -> None:
    """Toggle a scouting session — while on, every photo is auto-tagged «обследование поля»
    (no species, no review), so the agronomist doesn't re-pick the category each time."""
    key = f"flagleaf:scoutmode:{user['tg_user_id']}"
    if await _web_redis.get(key):
        await _web_redis.delete(key)
        await message.answer("Режим обследования выключен. Фото снова с выбором вида.")
    else:
        await _web_redis.set(key, "1", ex=12 * 3600)        # auto-off after 12 h
        await message.answer(
            "🔍 Режим обследования включён.\n"
            "Все присылаемые фото идут как обследование поля — без выбора вида и без проверки. "
            "Снимайте всё поле, включая чистые участки.\n\n/scout — выключить (или само через 12 часов).")


@router.message(Command("weblogin"))
async def cmd_weblogin(message: Message, user) -> None:
    """Issue a one-time 6-digit code to log in on ai.flagleaf.ru (web photo upload for labeling)."""
    code = f"{secrets.randbelow(900000) + 100000}"
    await _web_redis.set(f"flagleaf:weblogin:{code}", str(user["tg_user_id"]), ex=300)
    await message.answer(
        "🔑 Код для входа на сайт Flagleaf:\n\n"
        f"      {code}\n\n"
        "Откройте 👉 ai.flagleaf.ru/app и введите код. Действует 5 минут.")


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.message(Command("myemail"))
async def cmd_myemail(message: Message, command: CommandObject, user) -> None:
    """Let an agronomist attach their own email so they can get login codes by email
    (no Telegram/VPN needed afterwards)."""
    email = (command.args or "").strip().lower()
    if not _EMAIL_RE.match(email):
        await message.answer(
            "Укажите ваш email, например:\n/myemail ivan@example.ru\n\n"
            "После этого код для входа на сайт можно получать на почту — без Telegram.")
        return
    if await set_user_email(user["tg_user_id"], email):
        await message.answer(
            f"Готово ✓ Привязал {email}.\n"
            "Теперь на ai.flagleaf.ru/app можно войти по email — код придёт на почту.")
    else:
        await message.answer("Этот email уже привязан к другому пользователю. Укажите другой.")


@router.message(Command("setemail"))
async def cmd_setemail(message: Message, command: CommandObject, user) -> None:
    """Admin: attach an email to another user — /setemail <tg_id> <email>."""
    if not _is_admin(user):
        await message.answer("Эта команда доступна только администратору.")
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[0].lstrip("-").isdigit() or not _EMAIL_RE.match(parts[1].lower()):
        await message.answer("Как привязать email агроному:\n/setemail 123456789 ivan@example.ru")
        return
    tg_id, email = int(parts[0]), parts[1].strip().lower()
    if await set_user_email(tg_id, email):
        await message.answer(f"Готово ✓ {email} привязан к {tg_id}.")
    else:
        await message.answer("Не вышло: такого активного пользователя нет, или email уже занят.")


@router.message(Command("plan"))
async def cmd_plan(message: Message, command: CommandObject, user) -> None:
    """Pilot v2: generate a treatment plan for a field from its history + scouting +
    the registered-product catalog. Favours treating only what needs treating."""
    q = (command.args or "").strip()
    if not q:
        await message.answer(
            "Составлю план работ по полю. Укажите поле, например:\n/plan 121/140\n\n"
            "План опирается на историю поля, последние обследования и зарегистрированные "
            "препараты — и подскажет, что можно НЕ обрабатывать.")
        return
    await message.answer("📋 Составляю план по полю — минутку…")
    try:
        plan = await generate_field_plan(q, user["farm_id"], ran_by=user["tg_user_id"])
    except Exception:
        logger.exception("cmd_plan failed")
        plan = "Не удалось составить план. Попробуйте позже."
    await message.answer(plan)


@router.message(Command("setprice"))
async def cmd_setprice(message: Message, command: CommandObject, user) -> None:
    """Admin: set a product's unit price for ₽ savings — /setprice Корсар, ВРК = 1200 л."""
    if not _is_admin(user):
        await message.answer("Команда только для администратора.")
        return
    args = (command.args or "").strip()
    if "=" not in args:
        await message.answer("Формат: /setprice Корсар, ВРК = 1200 л\n(ед. — л или кг, цена за единицу в ₽)")
        return
    name, rhs = args.split("=", 1)
    name = name.strip()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(л|кг)", rhs.strip(), re.I)
    if not name or not m:
        await message.answer("Не понял. Пример: /setprice Корсар, ВРК = 1200 л")
        return
    price = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    await set_product_price(name, price, unit)
    await message.answer(f"✓ Цена сохранена: {name} — {price:g} ₽/{unit}. /prices — посмотреть все.")


@router.message(Command("prices"))
async def cmd_prices(message: Message, user) -> None:
    """Admin: current prices + which products from your fields' history still need one."""
    if not _is_admin(user):
        await message.answer("Команда только для администратора.")
        return
    prices = await get_product_prices()
    used = await get_protection_products(user["farm_id"])
    have, missing = [], []
    for prod in used:
        pr = prices.get((prod or "").strip().lower())
        (have if pr else missing).append(
            f"• {prod} — {pr['price']:g} ₽/{pr['unit']}" if pr else f"• {prod}")
    parts = []
    if have:
        parts.append("💰 Цены заданы:\n" + "\n".join(have))
    if missing:
        parts.append("❓ Без цены (нужны для расчёта экономии в ₽):\n" + "\n".join(missing)
                     + "\n\nДобавьте: /setprice Название = 1200 л")
    await message.answer("\n\n".join(parts) if parts else "По вашим полям нет препаратов в истории.")


@router.message(Command("savings"))
async def cmd_savings(message: Message, command: CommandObject, user) -> None:
    """Savings-log (admin). View recent plan runs, or record a realized outcome:
    /savings — список; /savings Поле 39 = точечно, экономия ~30% — записать результат по полю."""
    if not _is_admin(user):
        await message.answer("Команда только для администратора.")
        return
    args = (command.args or "").strip()
    if "=" in args:
        field_q, outcome = args.split("=", 1)
        field = await resolve_field(field_q.strip(), user["farm_id"])
        if not field:
            await message.answer(f"Поле не найдено: «{field_q.strip()}».")
            return
        ok = await annotate_latest_plan_run(field["id"], outcome.strip())
        await message.answer("✓ Результат записан в журнал." if ok
                             else "По этому полю ещё нет плана — сначала /plan.")
        return
    runs = await get_plan_runs(farm_id=user["farm_id"], limit=15)
    if not runs:
        await message.answer("Журнал планов пуст. Составьте план: /plan 121/140")
        return
    lines = ["📊 Журнал планов (экономия):"]
    for r in runs:
        d = r["created_at"].strftime("%d.%m") if r["created_at"] else ""
        cost = (f" · {float(r['baseline_cost']):,.0f} ₽".replace(",", " ")
                if r["baseline_cost"] is not None else "")
        lines.append(f"• {d} {r['field_name']}: база {r['baseline_passes']} обр.{cost}"
                     + (f"\n   → {r['outcome']}" if r["outcome"] else ""))
    lines.append("\nЗаписать результат: /savings Поле 39 = точечно, экономия ~30%")
    await message.answer("\n".join(lines))


@router.message(Command("field"))
async def cmd_field(message: Message, command: CommandObject, user) -> None:
    """Integrated data-layer card for one field (treatment history with
    active substances, protection rotation by season, weather, NDVI, catalog).
    Available to everyone (read-only)."""
    q = (command.args or "").strip()
    if not q:
        await message.answer("Укажите поле, например: /field 76/108")
        return
    # Order: farm overview → close-up → info card. Maps are best-effort — a
    # render/send failure must never stop the info card below.
    try:
        fid = await resolve_field_id(q, user["farm_id"])
        if fid is not None:
            polys = fieldmap.build_polys(await get_field_polygons())
            if any(p["id"] == fid for p in polys):
                overview = fieldmap.render_overview(polys, fid)
                closeup = fieldmap.render_closeup(polys, fid)
                await message.answer_photo(
                    BufferedInputFile(overview, "field_overview.png"),
                    caption="🗺️ Поле на карте хозяйства",
                )
                if closeup:
                    await message.answer_photo(
                        BufferedInputFile(closeup, "field_closeup.png"),
                        caption="📍 Поле крупно (с соседями)",
                    )
    except Exception:
        logger.exception("field map render failed for %s", q)
    await message.answer(await field_card_text(q, user["farm_id"]))


@router.message(Command("export"))
async def cmd_export(message: Message, command: CommandObject, user) -> None:
    """Export a field's operations as a CropWise-style multiprotocol .xlsx and
    send it as a Telegram document — the inverse of the import pipeline."""
    q = (command.args or "").strip()
    if not q:
        await message.answer("Укажите поле, например: /export 119")
        return
    from catalog.export_multiprotocol import build_multiprotocol  # openpyxl — lazy
    res = await build_multiprotocol(q, user["farm_id"])
    if not res:
        await message.answer(f"Поле не найдено: «{q}».")
        return
    fname, data = res
    await message.answer_document(
        BufferedInputFile(data, fname),
        caption="📑 Операции по полю (multiprotocol)",
    )


@router.message(Command("scan"))
async def cmd_scan(message: Message, user) -> None:
    """On-demand proactive NDVI check across the pilot fields — interprets each
    field's recent NDVI vs the same-crop norm and names only those needing a
    look. Always replies (unlike the weekly cron, which stays silent if normal)."""
    as_of, results = await ndvi_scan(user["farm_id"])
    await message.answer(format_digest(as_of, results))


@router.message(Command("stats"))
async def cmd_stats(message: Message, user) -> None:
    s = await get_user_stats(user["id"])
    collected, trained = await get_team_progress()
    goal = settings.team_photo_goal
    week = int(s["week"])
    # Weekly goal is 15–30 photos (the single success metric).
    if week >= 15:
        progress = "цель недели выполнена ✅"
    else:
        progress = f"до цели недели (15) осталось {15 - week}"
    await message.answer(
        "Ваша статистика:\n"
        f"• Сегодня: {int(s['today'])}\n"
        f"• За эту неделю: {week} — {progress}\n"
        f"• Дней с фото на этой неделе: {int(s['active_days'])}\n"
        f"• Всего сохранено: {int(s['total'])}\n"
        f"• 🎓 Уже обучают ИИ (прошли разметку): {int(s['labeled'])}\n\n"
        f"🌱 Вклад команды: собрано {collected} из {goal} фото "
        f"(прошли разметку и обучают ИИ: {trained}). Спасибо за общий результат!"
    )


# ---------- /finish: resume an interrupted photo upload ----------
# The FSM state in Redis expires after ~10 min of inactivity, but the
# submission row sits in Postgres at status=awaiting_metadata forever.
# /finish picks the user's most recent stuck submission and re-enters the
# FSM at whichever step they didn't complete (category / subcategory / comment).
# The existing on_category / on_subcategory / on_*_comment handlers do the rest.

@router.message(Command("finish"))
async def cmd_finish(message: Message, state: FSMContext, user) -> None:
    if await state.get_state() is not None:
        await message.answer(
            "Вы сейчас в процессе загрузки. Сначала /cancel, потом /finish."
        )
        return

    pending = await get_pending_submission(user["id"])
    if pending is None:
        await message.answer("Незавершённых фото нет — всё сохранено ✓")
        return

    await state.update_data(
        submission_id=str(pending["id"]), field_id=pending["field_id"]
    )
    field_label = pending["field_name"] or "неизвестное поле"
    when = f"{pending['created_at']:%d.%m %H:%M}"
    intro = f"Продолжаем фото с поля {field_label} от {when}."

    # Resume at whichever step is still missing.
    if pending["category"] is None:
        await state.set_state(PhotoForm.category)
        await message.answer(f"{intro} Что на фото?", reply_markup=_category_kb())
    elif pending["category"] == "weed" and pending["subcategory"] is None:
        species = await get_top_species()
        await state.set_state(PhotoForm.subcategory)
        await message.answer(
            f"{intro} Какой вид? (можно пропустить)",
            reply_markup=_species_kb(species),
        )
    elif pending["category"] == "disease" and pending["subcategory"] is None:
        await state.set_state(PhotoForm.subcategory)
        await message.answer(
            f"{intro} Какая болезнь? (можно пропустить)",
            reply_markup=_disease_kb(),
        )
    elif pending["category"] == "pest" and pending["subcategory"] is None:
        await state.set_state(PhotoForm.subcategory)
        await message.answer(
            f"{intro} Какой вредитель? (можно пропустить)",
            reply_markup=_pest_kb(),
        )
    else:
        # Category set (and subcategory if weed) — only the comment remains.
        await state.set_state(PhotoForm.comment)
        await message.answer(f"{intro} Комментарий? Текстом или голосом. Или /skip.")


# ---------- /adduser: admin whitelists a new agronomist ----------

def _is_admin(user) -> bool:
    return user["role"] == "admin" or user["tg_user_id"] in settings.admin_ids


@router.message(Command("unsynced"))
async def cmd_unsynced(message: Message, user) -> None:
    """Admin: bot-logged operations whose CropWise push never confirmed. The local
    history row is safe; this surfaces the ones to re-enter in CropWise by hand."""
    if not _is_admin(user):
        await message.answer("Команда только для администратора.")
        return
    rows = await get_unsynced_bot_treatments()
    if not rows:
        await message.answer("✅ Все записанные операции ушли в CropWise.")
        return
    lines = ["⚠️ <b>Не ушли в CropWise</b> (запись в истории поля есть, повторите в CropWise вручную):"]
    for r in rows:
        d = r["treatment_date"].isoformat() if r["treatment_date"] else "—"
        prod = f" · {r['product']} {r['dose'] or ''}".rstrip() if r["product"] else ""
        lines.append(f"• {d} · {r['field_name']} · {r['operation']}{prod}")
    await message.answer("\n".join(lines), parse_mode="HTML")


# "What's new" feed. Each item has a stable, increasing id; /announce posts only items
# newer than what this chat has already seen (watermark in Redis). Append new features
# with higher ids; never renumber existing ones.
_ANNOUNCEMENTS = [
    (1, "📝 <b>Запись обработок голосом или текстом</b>\n"
        "Запишите выполненную операцию прямо в боте — голосом или текстом, например: "
        "«опрыскал поле 119 Корсаром 1.5 л/га от сорняков». Бот сам определит поле, "
        "препарат, норму и дату, а чего не хватит — переспросит. После подтверждения "
        "запись попадёт и в историю поля, и в CropWise."),
    (2, "🌿 <b>Подсказка по сорняку на фото</b>\n"
        "Не уверены, какой это сорняк? При загрузке фото нажмите «Другой» — бот по снимку "
        "предложит 2–3 вероятных варианта. Выберите подходящий или впишите свой."),
    (3, "✅ <b>Проверка фото старшим агрономом</b>\n"
        "Загруженные фото сначала уходят на проверку Алмасу. Он подтверждает или поправляет "
        "вид/поле/культуру — и фото идёт дальше. Если что-то исправит, вы получите уведомление."),
    (4, "💬 <b>Спросите бота про поле — как у коллеги</b>\n"
        "Напишите боту вопрос своими словами — он ответит по данным CropWise (последние "
        "обработки, культура, площадь). Примеры:\n"
        "• «Какая обработка была недавно на поле 119?»\n"
        "• «Чем и когда обрабатывали 76/108 в этом сезоне?»\n"
        "• «Какая культура на поле 144 и какая площадь?»\n"
        "• «Чем лучше обработать сою от злаковых сорняков?» — на общие агрономические "
        "вопросы тоже отвечает.\n"
        "📍 Можно прислать геопозицию (скрепка 📎 → «Геопозиция»): бот сам определит, на "
        "каком вы поле, и дальше спрашивайте просто «что делали на этом поле?» или «когда "
        "тут последний раз опрыскивали?»."),
    (5, "📋 <b>Задания машин — в один шаг</b> (для оператора)\n"
        "Отчёт из Max можно просто вставить в бот: он разберёт операцию, машину, "
        "механизатора, препараты и поля, покажет предпросмотр и по кнопке создаст "
        "агрооперации в CropWise — останется только проверить."),
    (6, "🤝 <b>Бот подскажет, как с ним работать</b>\n"
        "Спросите своими словами — «как записать обработку?» или «как правильно "
        "сфотографировать сорняк?» — и бот объяснит по-простому. Коротко про фото: "
        "дневной свет, чёткий фокус, два кадра (весь сорняк целиком и крупный план "
        "листа/соцветия), растение в центре кадра."),
    (7, "🔢 <b>Поиск поля по номеру — точнее</b>\n"
        "Исправили ошибку: раньше при запросе «поле 47» бот мог показать «поле 147». "
        "Теперь номер поля ищется точно."),
    (8, "📋 <b>Задания машин: сверка с планом агро работ</b> (для оператора)\n"
        "При вставке отчёта бот создаёт агрооперацию, только если её вид работ есть в "
        "«плане агро работ» поля, и сразу привязывает операцию к плану. Если вида работ "
        "в плане нет — бот пропустит это поле и подскажет добавить вид работ в план "
        "(на Камазы план агро работ не нужен)."),
    (9, "📸 <b>Определить сорняк/болезнь по фото — сразу с рекомендацией</b>\n"
        "Пришлите фото и в подписи задайте вопрос, например «что это за сорняк и чем "
        "обработать?». Бот определит объект, оценит уверенность, подскажет похожие варианты, "
        "что проверить в поле, меры борьбы и подходящие препараты — с учётом культуры на "
        "вашем поле. Фото без вопроса, как и раньше, идёт в разметку."),
    (10, "💊 <b>Подбор препаратов — конкретно и безопасно</b>\n"
        "На вопрос вроде «чем обработать сою от осота?» бот теперь отвечает структурно: что "
        "это за объект, меры борьбы, конкретные ЗАРЕГИСТРИРОВАННЫЕ препараты с нормами и "
        "производителем (Syngenta, BASF, Bayer, Август, Щёлково Агрохим и др.) и когда "
        "обрабатывать. Не предложит то, что повредит самой культуре, и при необходимости "
        "сошлётся на научные источники."),
    (11, "📝 <b>Запись операций — удобнее</b>\n"
        "Можно записать операцию сразу на несколько полей одним сообщением («опрыскал поля "
        "262, 252, 251 …»), а также работы без привязки к полю — подвоз/закачку воды, "
        "грейдирование дорог, покос (КамАЗ/ГАЗ/техника). Если механизаторов-однофамильцев "
        "несколько — добавьте имя или отчество, бот выберет нужного."),
    (12, "📧 <b>Вход на сайт загрузки фото — по почте, без Telegram</b>\n"
         "На ai.flagleaf.ru/app теперь можно войти по электронной почте: введите свой email, "
         "получите код в письме и войдите — Telegram и VPN больше не нужны. Чтобы привязать "
         "почту, отправьте боту команду <code>/myemail ваш@адрес.ru</code> (один раз). "
         "Вход на сайте сохраняется на 90 дней."),
    (13, "🔍 <b>Обследование поля — новый режим</b>\n"
         "Теперь главное — не искать отдельный сорняк, а снимать состояние всего поля. Включите "
         "«Режим обследования» в приложении (или команду <code>/scout</code> в боте) — и все фото идут как "
         "обследование, без выбора вида. Снимайте проходом весь участок: важно видеть, какие сорняки и в "
         "какой фазе, чтобы поймать срок обработки по ЭПВ."),
    (14, "🎥 <b>Видео обследования с голосовым комментарием</b>\n"
         "В режиме обследования можно снять короткое видео (до 3 минут) и прямо в нём проговорить голосом, "
         "что видите — «тут осот, плотность высокая…». Бот сам распознает речь и добавит её к данным поля. "
         "Без сети видео сохранится на телефоне и отправится, когда появится интернет."),
    (15, "📋 <b>План по полю</b>\n"
         "Команда <code>/plan 39</code> (или «План по полю» в приложении) собирает спектр сорняков по "
         "обследованию, историю поля и препараты, которыми хозяйство реально работает, и подсказывает: на "
         "какой стадии сорняки и пора ли обрабатывать (ЭПВ), каким зарегистрированным препаратом и в какой "
         "норме, хватит ли одной обработки или нужна вторая. Поле обрабатывается сплошь — решение по сроку, "
         "препарату и норме за Вами."),
    (16, "🎯 <b>Контрольные поля</b>\n"
         "Вверху экрана загрузки — список контрольных полей, которые нужно обследовать регулярно (раз в "
         "неделю). Цвет показывает, давно ли вы там были: зелёный — до 7 дней, жёлтый — 8–10, красный — пора "
         "идти. Если поле «покраснело», придёт напоминание."),
    (17, "🎤 <b>Голосовой комментарий и любое поле</b>\n"
         "В приложении комментарий к фото можно надиктовать голосом — нажмите 🎤 рядом с полем «Комментарий». "
         "И теперь доступно любое поле хозяйства: при загрузке введите его номер (например 39 или 76/108)."),
    (18, "🎥 <b>Видео обследования — на проверку старшему агроному</b>\n"
         "Теперь ваши видео с обследования сначала уходят на проверку Алмасу — так же, как фото. Он "
         "просматривает запись (и расшифровку речи), подтверждает — и наблюдение попадает в план по полю. "
         "Снимайте и комментируйте как обычно; ничего дополнительно делать не нужно."),
    (19, "✅ <b>«Мои загрузки» — проверьте, что всё дошло</b>\n"
         "В приложении под кнопкой загрузки появился список «Мои загрузки»: там видно каждое ваше фото и "
         "видео с сервера, с полем, временем и статусом (принято / ждёт разметки / на проверке). Так можно "
         "убедиться, что загрузка прошла успешно. Кнопка ⟳ — обновить список."),
]

_announce_redis = None


def _announce_store():
    global _announce_redis
    if _announce_redis is None:
        import redis.asyncio as aioredis
        _announce_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _announce_redis


@router.message(Command("announce"))
async def cmd_announce(message: Message, user) -> None:
    key = f"flagleaf:announce_seen:{message.chat.id}"
    rc = _announce_store()
    try:
        seen = int(await rc.get(key) or 0)
    except Exception:
        logger.exception("announce watermark read failed")
        seen = 0
    fresh = [(i, t) for i, t in _ANNOUNCEMENTS if i > seen]
    if not fresh:
        await message.answer("Пока ничего нового с прошлого раза 👍")
        return
    await message.answer("📣 <b>Новое в боте Flagleaf:</b>", parse_mode="HTML")
    for _, text_msg in fresh:
        await message.answer(text_msg, parse_mode="HTML")
        await asyncio.sleep(0.3)
    try:
        await rc.set(key, max(i for i, _ in fresh))
    except Exception:
        logger.exception("announce watermark save failed")


@router.message(Command("all"))
async def cmd_all(message: Message, user) -> None:
    """Recent uploads from EVERY agronomist. /history and /stats are per-user
    (each person sees only their own), so this is the shared window into what
    the whole team has sent. Available to everyone (read-only)."""
    rows = await get_all_recent_submissions()
    if not rows:
        await message.answer("Пока нет ни одной загрузки.")
        return

    lines = []
    counts = await get_team_week_counts()
    if counts:
        head = ", ".join(f"{c['full_name'] or '—'}: {int(c['week'])}" for c in counts)
        lines.append(f"📊 За эту неделю — {head}")
        lines.append("")
    lines.append("Последние загрузки (все агрономы):")

    for r in rows:
        when = f"{r['created_at']:%d.%m %H:%M}"
        label = CATEGORY_LABELS.get(r["category"], r["category"] or "—")
        status = STATUS_RU.get(r["status"], r["status"])
        parts = [when, r["uploader"] or "—", r["field_name"] or "поле?", label]
        if r["species_name"]:
            parts.append(r["species_name"])
        line = " · ".join(parts) + f"  [{status}]"

        comment = r["comment_text"] or r["comment_voice_text"]
        if comment:
            snippet = comment if len(comment) <= 40 else comment[:39] + "…"
            icon = "💬" if r["comment_text"] else "🎤"
            line += f"\n  {icon} {snippet}"
        elif r["comment_voice_url"]:
            line += "\n  🎤 голосовой комментарий"
        lines.append(f"• {line}")

    await message.answer("\n".join(lines))


@router.message(Command("addweed"))
async def cmd_addweed(message: Message, command: CommandObject, user) -> None:
    """Admin: add a new weed species to the annotation dictionary (a CVAT label), so a weed
    the annotator flagged as «unknown» can be labelled going forward."""
    if not _is_admin(user):
        await message.answer("Эта команда доступна только администратору.")
        return
    name = re.sub(r"[^a-z0-9_]", "", (command.args or "").strip().lower().replace(" ", "_"))
    if not name:
        await message.answer(
            "Добавить новый вид сорняка в словарь разметки:\n"
            "/addweed cirsium_arvense\n\n"
            "Код — латиницей (латинское название через _). После добавления этот сорняк "
            "можно будет размечать в CVAT.")
        return
    try:
        ok, info = await asyncio.to_thread(add_cvat_label, name)
    except Exception:
        logger.exception("addweed failed")
        await message.answer("Не удалось добавить класс — попробуйте позже.")
        return
    if ok:
        await message.answer(f"✅ Класс «{name}» добавлен в словарь разметки (цвет {info}). "
                             "Теперь этот сорняк можно размечать в CVAT.")
    else:
        await message.answer(f"⚠️ {info}")


@router.message(Command("adduser"))
async def cmd_adduser(message: Message, command: CommandObject, user) -> None:
    if not _is_admin(user):
        await message.answer("Эта команда доступна только администратору.")
        return

    tg_id: int | None = None
    name: str | None = None

    if command.args:
        parts = command.args.split(maxsplit=1)
        if parts[0].lstrip("-").isdigit():
            tg_id = int(parts[0])
            name = parts[1].strip() if len(parts) > 1 else None

    if tg_id is None:
        await message.answer(
            "Как добавить агронома:\n"
            "/adduser 123456789 Иван Петров\n\n"
            "Номер (123456789) человек видит сам, когда впервые нажимает Start — "
            "пусть пришлёт его вам."
        )
        return

    added = await add_agronomist(tg_id, name, user["farm_id"])
    who = added["full_name"] or str(tg_id)
    if added["role"] == "admin":
        await message.answer(f"{who} — администратор, доступ уже есть.")
    else:
        await message.answer(
            f"Готово ✓ {who} добавлен(а) как агроном. "
            "Попросите нажать Start — бот его впустит."
        )


@router.message(Command("removeuser"))
async def cmd_removeuser(message: Message, command: CommandObject, user) -> None:
    if not _is_admin(user):
        await message.answer("Эта команда доступна только администратору.")
        return

    arg = (command.args or "").strip()
    if not arg.lstrip("-").isdigit():
        await message.answer(
            "Как убрать доступ:\n"
            "/removeuser 123456789\n\n"
            "Номер можно посмотреть в /adduser или в списке пользователей."
        )
        return

    tg_id = int(arg)
    if tg_id == user["tg_user_id"]:
        await message.answer("Нельзя убрать доступ у самого себя.")
        return

    removed = await deactivate_user(tg_id)
    if removed is None:
        await message.answer("Активный пользователь с таким номером не найден.")
        return

    who = removed["full_name"] or str(tg_id)
    await message.answer(
        f"Готово ✓ доступ для {who} отозван. Снимки и история сохранены."
    )


# ---------- /problem: collect a free-text report, forward to admins ----------

@router.message(Command("problem"))
async def cmd_problem(message: Message, state: FSMContext) -> None:
    await state.set_state(ProblemForm.waiting)
    await message.answer(
        "Опишите проблему или вопрос одним сообщением — я передам администратору. "
        "Или /cancel, чтобы отменить."
    )


@router.message(ProblemForm.waiting, F.text)
async def on_problem_text(message: Message, state: FSMContext, user) -> None:
    await state.clear()
    name = user["full_name"] or "без имени"
    report = (
        f"⚠️ Сообщение о проблеме от {name} (tg id {message.from_user.id}):\n\n"
        f"{message.text}"
    )
    delivered = False
    for admin_id in settings.admin_ids:
        try:
            await message.bot.send_message(admin_id, report)
            delivered = True
        except Exception:
            continue
    if delivered:
        await message.answer("Спасибо! Передал администратору.")
    else:
        await message.answer(
            "Записал, но не удалось уведомить администратора автоматически. "
            "Свяжитесь с ним напрямую, если вопрос срочный."
        )


# ---------- photo flow (the core) ----------

async def _start_photo_flow(
    message: Message,
    state: FSMContext,
    user,
    file_id: str,
    mime: str,
    width: int | None,
    height: int | None,
) -> None:
    """Shared kickoff for both 'Photo'-sent and 'File'-sent images:
    cache file metadata in FSM, prompt for field."""
    await state.set_state(PhotoForm.field)
    await state.update_data(file_id=file_id, mime=mime, width=width, height=height)
    await message.answer("Принял фото. Пара уточнений:")

    fields = await get_demo_field_list(user["farm_id"])
    if not fields:
        await message.answer("Поля не настроены — обратитесь к администратору.")
        await state.clear()
        return
    await message.answer("На каком поле? (или «Другое поле» → введите номер)",
                         reply_markup=_fields_kb(fields))


# A photo CAPTIONED with a question («что это за сорняк и как бороться?») is a diagnosis
# request, not a labeling upload → answer it (structured, grounded) instead of the FSM.
_DIAG_CAPTION_RE = re.compile(
    r"что это|что за|какой это|какая это|определ|диагноз|распозна|"
    r"\bсорняк|болезн|вредител|чем\s+(?:обработать|бороться|травить|опрыс)|"
    r"как\s+(?:бороться|избав|убрать|справит)|\?", re.I)
_CROP_HINTS = [("подсолнечник", "подсолн"), ("соя", "соя"), ("соя", "сое"), ("соя", "сои"),
               ("пшеница", "пшениц"), ("кукуруза", "кукуруз"), ("ячмень", "ячмен"),
               ("рапс", "рапс"), ("сахарная свёкла", "свекл"), ("горох", "горох")]


async def _diag_crop(message: Message, state: FSMContext, user):
    """Best-effort known crop for the photo: named in the caption, else the last field
    in context (so we skip 'какая культура?' like the competitor can't). (crop, field_name)."""
    cap = (message.caption or "").lower().replace("ё", "е")
    for canon, pat in _CROP_HINTS:
        if pat in cap:
            return canon, None
    fn = (await state.get_data()).get("last_field_name")
    if fn:
        row = await resolve_field(fn, user["farm_id"])
        if row and row["crop"]:
            return row["crop"], row["name"]
    return None, None


async def _handle_photo_diagnosis(message: Message, state: FSMContext, user, file_id) -> None:
    await message.answer("🔎 Анализирую фото…")
    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass
    try:
        file = await message.bot.get_file(file_id)
        img = (await message.bot.download_file(file.file_path)).read()
        crop, field_name = await _diag_crop(message, state, user)
        from bot.diagnose import diagnose
        ans = await diagnose(img, message.caption, crop, field_name)
    except Exception:
        logger.exception("photo diagnosis failed")
        ans = None
    await message.answer(ans or (
        "Не удалось обработать фото автоматически (возможно, временный сбой). Опишите словами "
        "— какая культура, после какой обработки, какие симптомы — отвечу по описанию; либо "
        "повторите через минуту или загрузите фото обычным способом для разметки."))


@router.message(F.photo)
async def on_photo(message: Message, state: FSMContext, user) -> None:
    """Photo sent via Telegram's camera/gallery button. Telegram compresses
    to ~1280–2560 px on the long edge; for full original resolution the
    sender should use paperclip → File (see on_photo_document below)."""
    photo = message.photo[-1]  # largest variant Telegram offers
    if message.caption and _DIAG_CAPTION_RE.search(message.caption):
        await _handle_photo_diagnosis(message, state, user, photo.file_id)
        return
    await _start_photo_flow(
        message, state, user,
        file_id=photo.file_id, mime="image/jpeg",
        width=photo.width, height=photo.height,
    )


@router.message(F.document.mime_type.startswith("image/"))
async def on_photo_document(message: Message, state: FSMContext, user) -> None:
    """Photo sent as a File (paperclip → File). Telegram does NOT compress
    this path, so we get the original — typically 4000+ px on a modern phone
    vs ~1280 px via the camera button. Worth the small extra friction for
    detection on small targets (wide-field shots with many small weeds)."""
    doc = message.document
    if message.caption and _DIAG_CAPTION_RE.search(message.caption):
        await _handle_photo_diagnosis(message, state, user, doc.file_id)
        return
    # Telegram's Document object doesn't expose original image width/height
    # directly (only the thumbnail's). Leave dimensions as None — the
    # submissions.image_{width,height} columns are nullable, and downstream
    # CV reads dimensions from the image bytes anyway.
    await _start_photo_flow(
        message, state, user,
        file_id=doc.file_id, mime=doc.mime_type,
        width=None, height=None,
    )


async def _save_photo_for_field(msg: Message, state: FSMContext, user, field_id) -> None:
    """Download the cached photo, dedup, store it against `field_id` (None =
    off-pilot training photo, kept out of any field's records), then move on to
    the category question. Shared by the pilot-button, typed-number, and
    skip-off-pilot paths."""
    data = await state.get_data()
    path_seg = str(field_id) if field_id else "other"

    file = await msg.bot.get_file(data["file_id"])
    buffer = await msg.bot.download_file(file.file_path)
    img_bytes = buffer.read()
    img_hash = hashlib.sha256(img_bytes).hexdigest()

    # Dedup: a byte-identical photo this agronomist already sent (e.g. a
    # re-send after the bot seemed unresponsive). Skip it — don't re-upload,
    # don't ask the metadata questions again.
    dup = await find_duplicate_submission(user["id"], img_hash)
    if dup:
        when = f"{dup['created_at']:%d.%m %H:%M}"
        await state.clear()
        await msg.answer(
            f"📸 Это фото уже было загружено ранее ({when}). "
            f"Повторно сохранять не нужно — можно отправлять следующее."
        )
        return

    submission_id = str(uuid4())
    mime = data.get("mime", "image/jpeg")
    key = f"raw/{user['farm_id']}/{path_seg}/{date.today():%Y-%m-%d}/{submission_id}.{_ext_for_mime(mime)}"
    image_url = await upload_bytes(key, img_bytes, mime)

    await create_submission(
        submission_id, user["id"], field_id, image_url,
        data.get("width"), data.get("height"), image_hash=img_hash,
    )
    await state.update_data(submission_id=submission_id, field_id=field_id)
    if await _scout_mode_on(user["tg_user_id"]):       # scouting session → auto-tag, skip category
        await update_submission(submission_id, category="scouting")
        await state.update_data(category="scouting")
        await state.set_state(PhotoForm.comment)
        await msg.answer("🔍 Обследование. Комментарий? Текстом или голосом. Или /skip.")
    else:
        await state.set_state(PhotoForm.category)
        await msg.answer("Что на фото?", reply_markup=_category_kb())


@router.callback_query(PhotoForm.field, F.data.startswith("field:"))
async def on_field(callback: CallbackQuery, state: FSMContext, user) -> None:
    await _ack(callback)
    token = callback.data.split(":")[1]
    # "other" → ask for a field number so ANY of the farm's fields can be tagged
    # (not just the pilots shown as buttons); /skip there keeps it off-pilot.
    if token == "other":
        await state.set_state(PhotoForm.field_number)
        await callback.message.answer(
            "Введите номер поля — например 125 или 76/108.\n"
            "Или /skip, чтобы сохранить фото без привязки к полю."
        )
        return
    await _save_photo_for_field(callback.message, state, user, int(token))


@router.message(PhotoForm.field_number, Command("skip"))
async def on_field_number_skip(message: Message, state: FSMContext, user) -> None:
    # No field — off-pilot training photo (field_id NULL).
    await _save_photo_for_field(message, state, user, None)


@router.message(PhotoForm.field_number, F.text)
async def on_field_number(message: Message, state: FSMContext, user) -> None:
    typed = re.sub(r"^\s*(поле|field)\s*", "", message.text.strip(), flags=re.I).strip()
    matches = await find_fields_by_number(user["farm_id"], typed)
    if not matches:
        await message.answer(
            f"Поле «{typed}» не найдено. Проверьте номер (например 125 или 76/108) "
            "и пришлите ещё раз, или /skip — сохранить без поля."
        )
        return
    if len(matches) == 1:
        f = matches[0]
        await message.answer(f"Поле: {f['name']}")
        await _save_photo_for_field(message, state, user, f["id"])
        return
    # Same number in several field groups — let the agronomist pick which.
    rows = [
        [InlineKeyboardButton(text=f["name"], callback_data=f"field:{f['id']}")]
        for f in matches
    ]
    await state.set_state(PhotoForm.field)
    await message.answer(
        "Несколько полей с таким номером — выберите:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(PhotoForm.category, F.data.startswith("cat:"))
async def on_category(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    code = callback.data.split(":")[1]
    data = await state.get_data()
    await update_submission(data["submission_id"], category=code)
    await state.update_data(category=code)        # so _finalize can route scouting past review

    if code == "weed":
        species = await get_top_species()
        await state.set_state(PhotoForm.subcategory)
        await callback.message.answer(
            "Какой вид? (можно пропустить)", reply_markup=_species_kb(species)
        )
    elif code == "disease":
        await state.set_state(PhotoForm.subcategory)
        await callback.message.answer(
            "Какая болезнь? (можно пропустить)", reply_markup=_disease_kb()
        )
    elif code == "pest":
        await state.set_state(PhotoForm.subcategory)
        await callback.message.answer(
            "Какой вредитель? (можно пропустить)", reply_markup=_pest_kb()
        )
    else:
        await state.set_state(PhotoForm.comment)
        await callback.message.answer("Комментарий? Текстом или голосом. Или /skip.")


@router.callback_query(PhotoForm.subcategory, F.data.startswith("dis:"))
async def on_disease(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    value = callback.data.split(":", 1)[1]

    # "Другая болезнь" — branch to free-text input (reuses the subcategory_other
    # flow, same as weeds' "Другой").
    if value == "other":
        await state.set_state(PhotoForm.subcategory_other)
        await callback.message.answer("Введите название болезни (или /skip):")
        return

    data = await state.get_data()
    if value != "skip":
        ru = DISEASE_RU_BY_CODE.get(value)
        if ru:
            await update_submission(data["submission_id"], subcategory=ru)
    await state.set_state(PhotoForm.comment)
    await callback.message.answer("Комментарий? Текстом или голосом. Или /skip.")


@router.callback_query(PhotoForm.subcategory, F.data.startswith("pst:"))
async def on_pest(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    value = callback.data.split(":", 1)[1]

    # "Другой вредитель" — free-text (reuses the subcategory_other flow).
    if value == "other":
        await state.set_state(PhotoForm.subcategory_other)
        await callback.message.answer("Введите название вредителя (или /skip):")
        return

    data = await state.get_data()
    if value != "skip":
        ru = PEST_RU_BY_CODE.get(value)
        if ru:
            await update_submission(data["submission_id"], subcategory=ru)
    await state.set_state(PhotoForm.comment)
    await callback.message.answer("Комментарий? Текстом или голосом. Или /skip.")


@router.callback_query(PhotoForm.subcategory, F.data.startswith("sub:"))
async def on_subcategory(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    value = callback.data.split(":")[1]

    # "Другой" — the agronomist can't ID it. Offer photo-based guesses (in-RU
    # qwen3.6) as a memory jog, then fall back to free-text.
    if value == "other":
        await state.set_state(PhotoForm.subcategory_other)
        await _offer_weed_suggestions(callback, state)
        return

    data = await state.get_data()
    if value != "skip":
        species = await get_species(int(value))
        if species:
            await update_submission(data["submission_id"], subcategory=species["latin_name"])
    await state.set_state(PhotoForm.comment)
    await callback.message.answer("Комментарий? Текстом или голосом. Или /skip.")


async def _offer_weed_suggestions(callback: CallbackQuery, state: FSMContext) -> None:
    """On «Другой» for a weed: ask the in-RU vision model for ≤3 ranked guesses and
    show them as buttons (+ free-text). Any failure → plain free-text prompt."""
    data = await state.get_data()
    await callback.message.answer("Смотрю на фото, секунду… 🔎")
    guesses = []
    try:
        url = await get_submission_image_url(data["submission_id"])
        if url:
            img = await download_bytes(url)
            guesses = await suggest_species(img, await get_all_species())
    except Exception:
        logger.exception("weed suggestion failed")
    if not guesses:
        await callback.message.answer(
            "Не смог распознать вид по фото 🤷 Напишите название сами "
            "(или /skip, если не знаете).")
        return
    await state.update_data(weed_guesses=[g["ru"] for g in guesses])
    rows = [[InlineKeyboardButton(text=g["ru"], callback_data=f"wsug:{i}")]
            for i, g in enumerate(guesses)]
    rows.append([InlineKeyboardButton(text="✏️ Впишу сам", callback_data="wsug:own")])
    await callback.message.answer(
        "По фото похоже на (не точно — выберите или впишите своё):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(PhotoForm.subcategory_other, F.data.startswith("wsug:"))
async def on_weed_suggestion(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    await _drop_kb(callback)
    v = callback.data.split(":", 1)[1]
    data = await state.get_data()
    if v == "own":
        await callback.message.answer("Введите название вида (или /skip):")
        return
    guesses = data.get("weed_guesses") or []
    name = guesses[int(v)] if v.isdigit() and int(v) < len(guesses) else None
    if not name:
        await callback.message.answer("Введите название вида (или /skip):")
        return
    await update_submission(data["submission_id"], subcategory=name)
    await state.set_state(PhotoForm.comment)
    await callback.message.answer(
        f"Записал: «{name}». Комментарий? Текстом или голосом. Или /skip.")


@router.message(PhotoForm.subcategory_other, Command("skip"))
async def on_skip_subcategory_other(message: Message, state: FSMContext) -> None:
    await state.set_state(PhotoForm.comment)
    await message.answer("Комментарий? Текстом или голосом. Или /skip.")


@router.message(PhotoForm.subcategory_other, F.text)
async def on_subcategory_other_text(message: Message, state: FSMContext) -> None:
    # Free-text species name. Saved verbatim in submissions.subcategory.
    # Mixed-format on purpose: keyboard-picked rows store Latin (e.g.
    # "Setaria viridis"); free-text rows store whatever the agronomist
    # typed (Russian, regional name, sometimes both). /history's
    # COALESCE on weed_species.russian_name handles the display gracefully.
    # Promotion of frequently-typed names into the seed/keyboard is a
    # monthly review per labeling/schema_promotion_policy.md.
    data = await state.get_data()
    typed = message.text.strip()
    await update_submission(data["submission_id"], subcategory=typed)
    await state.set_state(PhotoForm.comment)
    await message.answer(f"Записал: «{typed}». Комментарий? Текстом или голосом. Или /skip.")


# reverse of CATEGORIES, for parsing a CA's typed category correction
_CAT_BY_RU = {label.lower(): code for label, code in CATEGORIES}
_CAT_BY_RU.update({"сорняки": "weed", "болезни": "disease", "вредители": "pest"})


def _review_caption(sub) -> str:
    cat = CATEGORY_LABELS.get(sub["category"], sub["category"] or "—")
    com = sub["comment_text"] or sub["comment_voice_text"]
    lines = [
        f"🔍 На проверку — прислал: {sub['submitter'] or '—'}",
        f"📍 Поле: {sub['field_name'] or '—'}",
        f"🏷 Категория: {cat}",
        f"🌿 Вид: {sub['subcategory'] or '—'}",
    ]
    if com:
        lines.append(f"💬 {com}")
    lines.append("\nПроверьте атрибуты. Исправьте при необходимости, затем отправьте на разметку.")
    return "\n".join(lines)


def _review_kb(sid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Поле", callback_data=f"rev:f:{sid}"),
         InlineKeyboardButton(text="✏️ Вид", callback_data=f"rev:s:{sid}")],
        [InlineKeyboardButton(text="✏️ Категория", callback_data=f"rev:c:{sid}"),
         InlineKeyboardButton(text="✏️ Комментарий", callback_data=f"rev:m:{sid}")],
        [InlineKeyboardButton(text="✅ Подтвердить и отправить на разметку",
                              callback_data=f"rev:ok:{sid}")],
    ])


async def _send_review_card(bot, chat_id, sid: str) -> None:
    sub = await get_submission_review(sid)
    if not sub:
        return
    try:
        img = await download_bytes(sub["image_url"])
        await bot.send_photo(chat_id, BufferedInputFile(img, "photo.jpg"),
                             caption=_review_caption(sub), reply_markup=_review_kb(sid))
    except Exception:
        logger.exception("send review card failed")
        await bot.send_message(chat_id, _review_caption(sub), reply_markup=_review_kb(sid))


async def _finalize(message: Message, state: FSMContext, user) -> None:
    data = await state.get_data()
    sid = data["submission_id"]
    await state.clear()
    today, week = await count_user_submissions(user["id"])
    # Only weed/disease/pest need CVAT annotation. Those from a junior go to the chief
    # first; from a chief/admin straight to the labeling queue. Everything else
    # (scouting/control/treatment_result/stress) is field-state → terminal 'stored',
    # no review, no CVAT.
    annotatable = data.get("category") in ("weed", "disease", "pest")
    # One team stream: Telegram uploads appear in the wall like web/native posts do —
    # that's also where the chief now reviews (👍/👎 on the message).
    try:
        await create_wall_from_submission(sid)
    except Exception:
        logger.exception("wall message for tg submission failed")
    if user["role"] == "agronomist" and annotatable:
        await update_submission(sid, status="pending_review")
        cas = await get_chief_agronomists(user["farm_id"])
        for ca in cas:
            await _send_review_card(message.bot, ca["tg_user_id"], sid)
        note = "Отправлено старшему агроному на проверку ✓" if cas else \
            "Сохранено ✓ (старший агроном не назначен — отправлено как есть)."
        if not cas:                       # no CA configured → don't strand it
            await update_submission(sid, status="ready_for_labeling")
        await message.answer(f"{note}\nЗа сегодня: {today}. За неделю: {week}.")
    else:
        await update_submission(sid, status="ready_for_labeling" if annotatable else "stored")
        await message.answer(f"Записал. Сохранено ✓\nЗа сегодня: {today}. За неделю: {week}.")


_REV_ATTR = {"f": "field", "s": "species", "c": "category", "m": "comment"}
_REV_PROMPT = {
    "field": "Введите номер поля:",
    "species": "Введите вид (русское или латинское название):",
    "category": "Введите категорию: сорняк / болезнь / вредитель / стресс / контроль / результат обработки",
    "comment": "Введите комментарий:",
}
_ATTR_RU = {"field": "поле", "species": "вид", "category": "категорию", "comment": "комментарий"}


@router.callback_query(F.data.startswith("rev:"))
async def on_review(callback: CallbackQuery, state: FSMContext, user) -> None:
    if user["role"] not in ("chief_agronomist", "admin"):
        await _ack(callback, "Только старший агроном проверяет фото.")
        return
    _, action, sid = callback.data.split(":", 2)
    if action in ("ok", "no"):
        sub = await get_submission_review(sid)
        if not sub or sub["status"] != "pending_review":   # already handled (app / other chief)
            await _ack(callback, "Уже обработано")
            await _drop_kb(callback)
            return
    if action == "ok":
        # Scouting videos are field-state, not annotation targets: a confirmed one goes
        # to terminal 'stored' (feeds /plan) instead of into the CVAT labeling queue.
        is_scouting = bool(sub and sub["category"] == "scouting")
        await update_submission(sid, status=approved_status(sub))
        await _drop_kb(callback)
        await _ack(callback, "Подтверждено ✓")
        await callback.message.answer(
            "✅ Видео обследования подтверждено." if is_scouting else "✅ Отправлено на разметку.")
        await notify_submitter_decision(callback.bot, sub, "approve")
        return
    if action == "no":                          # reject (video review card)
        await update_submission(sid, status="rejected")
        await _ack(callback, "Отклонено")
        await _drop_kb(callback)
        await callback.message.answer("🚫 Отклонено — в план не пойдёт.")
        await notify_submitter_decision(callback.bot, sub, "reject")
        return
    attr = _REV_ATTR.get(action)
    if not attr:
        await _ack(callback)
        return
    await state.set_state(CAReview.editing)
    await state.update_data(review_sid=sid, review_attr=attr)
    await _ack(callback)
    await callback.message.answer(_REV_PROMPT[attr])


@router.message(CAReview.editing, F.text)
async def on_review_edit(message: Message, state: FSMContext, user) -> None:
    data = await state.get_data()
    sid, attr = data.get("review_sid"), data.get("review_attr")
    if not sid or not attr:
        await state.clear()
        return
    val = message.text.strip()
    sub = await get_submission_review(sid)
    old = {"field": sub["field_name"], "species": sub["subcategory"],
           "category": CATEGORY_LABELS.get(sub["category"], sub["category"]),
           "comment": sub["comment_text"]}.get(attr) if sub else None
    if attr == "field":
        row = await resolve_field(val, user["farm_id"])
        if not row:
            await message.answer("Не нашёл такое поле. Введите номер ещё раз.")
            return
        await update_submission(sid, field_id=row["id"])
        newval = row["name"]
    elif attr == "species":
        await update_submission(sid, subcategory=val)
        newval = val
    elif attr == "category":
        code = _CAT_BY_RU.get(val.lower())
        if not code:
            await message.answer("Не понял категорию. Например: сорняк, болезнь, вредитель.")
            return
        await update_submission(sid, category=code)
        newval = CATEGORY_LABELS.get(code, val)
    else:  # comment
        await update_submission(sid, comment_text=val)
        newval = val
    # The correction itself finalizes the submission — straight to the annotator (or,
    # for a scouting video, terminal 'stored'). The junior is only notified.
    sub = await get_submission_review(sid)          # re-read: category may have just changed
    await update_submission(sid, status=approved_status(sub))
    await state.clear()
    if sub and sub["submitter_tg"]:
        try:
            await message.bot.send_message(
                sub["submitter_tg"],
                f"✏️ Старший агроном исправил {_ATTR_RU[attr]} в вашем фото: "
                f"«{old or '—'}» → «{newval}». Фото отправлено на разметку.")
        except Exception:
            logger.exception("notify submitter (correction) failed")
        try:
            await send_push(sub["submitter_tg"], "Фото исправлено ✏️",
                            f"Старший агроном поправил {_ATTR_RU[attr]} и отправил ваше фото в разметку.")
        except Exception:
            logger.exception("push submitter (correction) failed")
    await message.answer("Исправлено и отправлено на разметку ✓")


def _treatment_kb(treatments) -> InlineKeyboardMarkup:
    rows = []
    for t in treatments:
        prod = (t["product"] or "").strip()
        if len(prod) > 24:
            prod = prod[:23] + "…"
        when = f"{t['treatment_date']:%d.%m}" if t["treatment_date"] else "—"
        rows.append([InlineKeyboardButton(
            text=f"{prod} · {when}", callback_data=f"trt:{t['id']}")])
    rows.append([InlineKeyboardButton(
        text="Другое — напишу/наговорю", callback_data="trt:other")])
    rows.append([InlineKeyboardButton(
        text="Не связано / пропустить", callback_data="trt:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _ask_treatment_or_finalize(message: Message, state: FSMContext, user) -> None:
    """After the comment step the photo is FINALIZED (saved + counted) first, so
    the core metric is never at risk. Then — only for a real field with recorded
    treatments — we ask, as optional enrichment, which recent operation it relates
    to. If the agronomist ignores it, the photo is already banked."""
    data = await state.get_data()
    field_id = data.get("field_id")
    submission_id = data["submission_id"]
    treatments = await get_recent_treatments(field_id) if field_id else []
    await _finalize(message, state, user)  # save, count, "Сохранено ✓", clear state
    if not treatments:
        return
    # Re-seed a minimal state purely for the optional treatment link. Dates as
    # ISO strings → Redis-JSON-safe; the map lets the callback confirm
    # days-since without another DB round-trip.
    tmap = {
        str(t["id"]): {
            "p": t["product"],
            "d": t["treatment_date"].isoformat() if t["treatment_date"] else None,
        }
        for t in treatments
    }
    await state.set_state(PhotoForm.treatment)
    await state.update_data(submission_id=submission_id, treatments=tmap)
    await message.answer(
        "Это фото связано с недавней обработкой поля? (по желанию)",
        reply_markup=_treatment_kb(treatments),
    )


@router.message(PhotoForm.comment, Command("skip"))
async def on_skip_comment(message: Message, state: FSMContext, user) -> None:
    await _ask_treatment_or_finalize(message, state, user)


@router.message(PhotoForm.comment, F.voice)
async def on_voice_comment(message: Message, state: FSMContext, user) -> None:
    data = await state.get_data()
    file = await message.bot.get_file(message.voice.file_id)
    buffer = await message.bot.download_file(file.file_path)
    audio = buffer.read()
    key = f"voice/{date.today():%Y-%m-%d}/{data['submission_id']}.ogg"
    voice_url = await upload_bytes(key, audio, "audio/ogg")
    await update_submission(data["submission_id"], comment_voice_url=voice_url)

    await message.answer("Расшифровываю голосовое…")
    try:
        recognized = await transcribe(audio)
    except Exception:
        logger.exception("voice transcription failed for %s", data["submission_id"])
        recognized = ""

    if recognized:
        await update_submission(data["submission_id"], comment_voice_text=recognized)
        await message.answer(f"Распознал: «{recognized}»")
        # English translation for the (possibly non-Russian-speaking) annotator,
        # via YandexGPT grounded in the species dictionary (accurate weed names).
        try:
            english = await translate_ru_to_en(recognized)
        except Exception:
            logger.exception("voice translation failed for %s", data["submission_id"])
            english = ""
        if english:
            await update_submission(data["submission_id"], comment_voice_text_en=english)
    else:
        await message.answer("Не удалось распознать речь — голосовое сохранил как есть.")

    await _ask_treatment_or_finalize(message, state, user)


@router.message(PhotoForm.comment, F.text)
async def on_text_comment(message: Message, state: FSMContext, user) -> None:
    sid = (await state.get_data())["submission_id"]
    await update_submission(sid, comment_text=message.text)
    # English translation for the annotator (same species-grounded YandexGPT
    # as voice notes). Best-effort — backfill self-heals if this fails.
    try:
        english = await translate_ru_to_en(message.text)
    except Exception:
        logger.exception("text-comment translation failed for %s", sid)
        english = ""
    if english:
        await update_submission(sid, comment_text_en=english)
    await _ask_treatment_or_finalize(message, state, user)


# ---------- Russian free-text aliases for the slash commands ----------
# Telegram forbids Cyrillic in real /commands (names are a-z0-9_ only), so a
# Russian-speaking agronomist can instead just TYPE the word — «история»,
# «статистика», «помощь» — and get the same action. Scoped to StateFilter(None)
# so it NEVER hijacks text typed inside the photo/problem flows (a comment like
# "поле сухое" or a free-text species name stays what it is).

_TEXT_ALIASES = {
    "история": "history",
    "статистика": "stats",
    "стата": "stats",
    "поля": "fields",
    "поле": "fields",
    "закончить": "finish",
    "продолжить": "finish",
    "отмена": "cancel",
    "отменить": "cancel",
    "проблема": "problem",
    "вопрос": "problem",
    "помощь": "help",
    "справка": "help",
    "меню": "help",
    "все": "all",  # «всё» normalises to «все» below
    "осмотр": "scan",
    "проверка": "scan",
    "проверить": "scan",
    "запись": "log",
    "записать": "log",
    "журнал": "log",
    "экспорт": "export",
    "выгрузка": "export",
    "новости": "announce",
    "обновления": "announce",
}


def _alias_target(text: str | None) -> str | None:
    """Map the first word of a message to a command name, or None."""
    if not text:
        return None
    word = text.strip().split()[0].lower().replace("ё", "е").lstrip("/")
    return _TEXT_ALIASES.get(word)


async def _alias_filter(message: Message) -> dict | bool:
    target = _alias_target(message.text)
    return {"alias_target": target} if target else False


@router.message(StateFilter(None), F.text, _alias_filter)
async def on_text_alias(
    message: Message, state: FSMContext, user, alias_target: str
) -> None:
    if alias_target == "history":
        await cmd_history(message, user)
    elif alias_target == "stats":
        await cmd_stats(message, user)
    elif alias_target == "fields":
        # «поле 76/108» → that field's card (= /field). A bare «поле»/«поля»
        # → the pilot-field list (= /fields). Available to everyone.
        rest = message.text.strip().split(maxsplit=1)
        if len(rest) > 1:
            await cmd_field(message, CommandObject(command="field", args=rest[1]), user)
        else:
            await cmd_fields(message, user)
    elif alias_target == "announce":
        await cmd_announce(message, user)
    elif alias_target == "finish":
        await cmd_finish(message, state, user)
    elif alias_target == "cancel":
        await cmd_cancel(message, state)
    elif alias_target == "problem":
        await cmd_problem(message, state)
    elif alias_target == "help":
        await cmd_help(message, user)
    elif alias_target == "all":
        await cmd_all(message, user)
    elif alias_target == "scan":
        await cmd_scan(message, user)
    elif alias_target == "log":
        await cmd_log(message, state)
    elif alias_target == "export":
        rest = message.text.strip().split(maxsplit=1)
        await cmd_export(
            message, CommandObject(command="export", args=rest[1] if len(rest) > 1 else ""), user)


# ---------- treatment link: tie the photo to a recent field operation ----------
# The photo is already saved before these run (_ask_treatment_or_finalize
# finalizes first), so they only attach the optional link and clear state.

async def _drop_kb(callback: CallbackQuery) -> None:
    """Remove the inline keyboard so the buttons can't be re-tapped into a
    cleared state (which would hang the client spinner). Best-effort."""
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@router.callback_query(PhotoForm.treatment, F.data.startswith("trt:"))
async def on_treatment(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    await _drop_kb(callback)
    value = callback.data.split(":", 1)[1]

    if value == "skip":
        await state.clear()
        await callback.message.answer("Готово ✓ Без привязки к обработке.")
        return
    if value == "other":
        await state.set_state(PhotoForm.treatment_note)
        await callback.message.answer(
            "Что применяли и когда? Текстом или голосом. Или /skip."
        )
        return

    data = await state.get_data()
    info = (data.get("treatments") or {}).get(value)
    await update_submission(data["submission_id"], treatment_id=int(value))
    await state.clear()

    msg = "🧪 Отмечено."
    if info:
        prod = info.get("p") or "обработка"
        msg = f"🧪 Связано с обработкой «{prod}»."
        if info.get("d"):
            try:
                days = (date.today() - date.fromisoformat(info["d"])).days
                msg = f"🧪 Отмечено: фото через {days} дн. после обработки «{prod}»."
            except ValueError:
                pass
    await callback.message.answer(msg)


@router.callback_query(F.data.startswith("trt:"))
async def on_treatment_stale(callback: CallbackQuery) -> None:
    """A treatment button tapped after the step already finished (state cleared,
    e.g. a double-tap). Just acknowledge so the client spinner doesn't hang."""
    await _ack(callback)
    await _drop_kb(callback)


@router.message(PhotoForm.treatment_note, Command("skip"))
async def on_skip_treatment_note(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Готово ✓ Без привязки к обработке.")


@router.message(PhotoForm.treatment_note, F.voice)
async def on_treatment_note_voice(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    file = await message.bot.get_file(message.voice.file_id)
    buffer = await message.bot.download_file(file.file_path)
    audio = buffer.read()
    await message.answer("Расшифровываю голосовое…")
    try:
        recognized = await transcribe(audio)
    except Exception:
        logger.exception("treatment-note transcription failed for %s", data["submission_id"])
        recognized = ""
    await state.clear()
    if recognized:
        await update_submission(data["submission_id"], treatment_note=recognized)
        await message.answer(f"🧪 Записал: «{recognized}»")
    else:
        await message.answer("Не удалось распознать речь — обработку не записал.")


@router.message(PhotoForm.treatment_note, F.text)
async def on_treatment_note_text(message: Message, state: FSMContext) -> None:
    await update_submission(
        (await state.get_data())["submission_id"], treatment_note=message.text.strip()
    )
    await state.clear()
    await message.answer("🧪 Записал.")


# ---------- operation logging: log a field operation by voice/free text --------
# The agronomist describes what was done («опрыскал 119 Корсаром 1.5 л/га»);
# YandexGPT parses it, we resolve the field + active substance, show a one-line
# confirmation, and on ✓ it lands in field_treatments (source='bot'). Entered via /log,
# the «запись» text alias, or a free-text operation statement.

_OP_CAT_RU = {
    "tillage": "обработка почвы", "sowing": "сев",
    "fertilizer": "внесение удобрений", "protection": "опрыскивание/СЗР",
    "harvest": "уборка", "other": "операция",
}


def _op_date(s: str) -> date:
    s = (s or "today").strip().lower()
    if s in ("today", "сегодня", ""):
        return date.today()
    if s in ("yesterday", "вчера"):
        return date.today() - timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return date.today()


def _op_summary(op: dict) -> str:
    fields = op.get("fields") or []
    if len(fields) > 1:
        head = f"📍 Поля ({len(fields)}): " + ", ".join(f["name"] for f in fields)
    else:
        head = f"📍 {op['field_name']}" + (f" · {op['crop']}" if op["crop"] else "")
    lines = ["Записать операцию?", head, f"🛠 {op['operation']}"]
    if op["product"]:
        lines.append(f"📦 {op['product']}" + (f" ({op['dv']})" if op["dv"] else ""))
    bits = [b for b in (op["dose"], op["target"]) if b]
    if bits:
        lines.append("• " + " · ".join(bits))
    if len(fields) <= 1 and op["area"]:
        lines.append(f"📐 {op['area']:g} га")
    lines.append(f"📅 {date.fromisoformat(op['date']):%d.%m.%Y}")
    return "\n".join(lines)


def _oplog_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✓ Сохранить", callback_data="oplog:save"),
        InlineKeyboardButton(text="✗ Отмена", callback_data="oplog:cancel"),
    ]])


async def _start_oplog(target, state: FSMContext) -> None:
    await state.set_state(OpLogForm.awaiting)
    await target.answer(
        "Опишите операцию — текстом или голосом.\n"
        "Например: «опрыскал 119 Корсаром 1.5 л/га от сорняков». Или /cancel."
    )


@router.message(Command("log"))
async def cmd_log(message: Message, state: FSMContext) -> None:
    await _start_oplog(message, state)


@router.callback_query(F.data == "oplog:start")
async def on_oplog_start(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    await _drop_kb(callback)
    await _start_oplog(callback.message, state)


@router.callback_query(F.data == "oplog:none")
async def on_oplog_none(callback: CallbackQuery) -> None:
    await _ack(callback)
    await _drop_kb(callback)


# What the bot will ask back for when the agronomist's note is missing a required
# slot (one question at a time). Field is always required; product+dose for any
# operation that applies a substance; crop if the field has none on record.
_SLOT_Q = {
    "field": "На каком поле? Укажите номер, например «119».",
    "product": "Какой препарат или удобрение вносили? Например «Корсар».",
    "dose": "Какая норма расхода? Например «1.5 л/га».",
    "crop": "Какая культура на этом поле?",
}


def _field_entry(field) -> dict:
    return {"id": field["id"], "name": field["name"], "crop": field["crop"],
            "area": float(field["area_ha"]) if field["area_ha"] is not None else None}


def _field_entry_from_op(op: dict) -> dict:
    """Fallback field entry from the op's single-field mirror (defensive)."""
    return {"id": op["field_id"], "name": op["field_name"],
            "crop": op["crop"], "area": op["area"]}


def _apply_field(op: dict, field) -> None:
    op["field_id"] = field["id"]
    op["field_name"] = field["name"]
    op["crop"] = field["crop"]
    if op["area"] is None and field["area_ha"] is not None:
        op["area"] = float(field["area_ha"])
    op["fields"] = [_field_entry(field)]   # canonical list; mirror above kept for single-field code


def _op_missing(op: dict) -> list:
    """Required slots still empty, in the order we'll ask for them."""
    miss = []
    if not op.get("field_id"):
        miss.append("field")
    if op["category"] in ("protection", "fertilizer", "sowing"):
        if not op.get("product"):
            miss.append("product")
        elif not op.get("dose"):
            miss.append("dose")
    if not op.get("crop"):
        miss.append("crop")
    return miss


async def _continue_oplog(message: Message, state: FSMContext, op: dict) -> None:
    """Ask for the next missing slot, or — when complete — show the confirm card."""
    miss = _op_missing(op)
    if miss:
        await state.update_data(op=op, slot=miss[0])
        await state.set_state(OpLogForm.filling)
        await message.answer(_SLOT_Q[miss[0]])
        return
    await state.update_data(op=op)
    await state.set_state(OpLogForm.confirm)
    # Conflict check: warn if a colleague (or earlier entry) already logged the
    # same product on this field today, so the agronomist can avoid a duplicate.
    # Single-field only — a multi-field log is checked per row at save time.
    summary = _op_summary(op)
    dups = [] if len(op.get("fields") or []) > 1 else await find_similar_treatment(
        op["field_id"], date.fromisoformat(op["date"]), op["category"], op["product"])
    if dups:
        who = ", ".join(sorted({d["operator"] for d in dups if d["operator"]})) or "кто-то"
        summary = (
            f"⚠️ На этом поле за {date.fromisoformat(op['date']):%d.%m} уже записана "
            f"обработка «{op['product']}» (записал: {who}).\n"
            f"Если это та же операция — нажмите «Отмена».\n\n" + summary
        )
    await message.answer(summary, reply_markup=_oplog_confirm_kb())


def _group_of(name: str) -> str:
    """Отделение/группа from 'Поле 185 · Красное' → 'Красное' ('' if none)."""
    return name.split(" · ", 1)[1].strip() if " · " in (name or "") else ""


def _match_group(reply: str, choices) -> dict | None:
    r = (reply or "").strip().lower().replace("ё", "е")
    for c in choices:
        g = _group_of(c["name"]).lower().replace("ё", "е")
        if g and (r == g or r in g or g in r):
            return c
    return None


async def _set_field(message: Message, state: FSMContext, op: dict, ref: str, farm_id) -> bool:
    """Resolve a field reference into `op`. Across ALL farm fields, not just pilots.
    True if set; False if it asked a clarifying question (number repeats in several
    отделения, or not found) and left the FSM in OpLogForm.filling on the field slot."""
    ref = (ref or "").strip()
    cands = await find_fields_by_number(farm_id, ref)
    if len(cands) == 1:
        _apply_field(op, cands[0])
        return True
    if len(cands) > 1:                       # same number in several отделения → ask which
        groups = [g for g in (_group_of(c["name"]) for c in cands) if g]
        await state.update_data(op=op, slot="field", field_choices=[dict(c) for c in cands])
        await state.set_state(OpLogForm.filling)
        await message.answer(
            f"Поле {ref} есть в нескольких отделениях: {', '.join(groups)}.\n"
            f"Уточните отделение, например «{groups[0]}»." if groups else
            f"Поле {ref} встречается несколько раз — укажите название полностью.")
        return False
    row = await resolve_field(ref, farm_id)  # looser name/substring fallback
    if row:
        _apply_field(op, row)
        return True
    await state.update_data(op=op, slot="field")
    await state.set_state(OpLogForm.filling)
    await message.answer("Не нашёл такое поле. Укажите номер ещё раз, например «119».")
    return False


async def _set_fields(message: Message, state: FSMContext, op: dict, refs: list, farm_id) -> bool:
    """Resolve one OR several field refs into op['fields']. One ref → the existing
    single-field path (handles отделение disambiguation). Several → resolve each
    best-effort, proceed with the ones found, and flag any that didn't resolve."""
    refs = [r for r in (str(x).strip() for x in refs) if r]
    if len(refs) <= 1:
        return await _set_field(message, state, op, refs[0] if refs else "", farm_id)
    resolved, unresolved = [], []
    for ref in refs:
        cands = await find_fields_by_number(farm_id, ref)
        row = cands[0] if len(cands) == 1 else (
            None if cands else await resolve_field(ref, farm_id))
        (resolved if row else unresolved).append(_field_entry(row) if row else ref)
    if not resolved:
        await state.update_data(op=op, slot="field")
        await state.set_state(OpLogForm.filling)
        await message.answer("Не нашёл такие поля. Укажите номер, например «119».")
        return False
    op["fields"] = resolved
    first = resolved[0]
    op["field_id"], op["field_name"], op["crop"] = first["id"], first["name"], first["crop"]
    if op["area"] is None:
        op["area"] = first["area"]
    if unresolved:
        await message.answer("⚠️ Не распознал поля: " + ", ".join(unresolved)
                             + ". Запишу только распознанные — остальные залогируйте отдельно.")
    await state.update_data(op=op)
    return True


async def _handle_machine_task(message: Message, state: FSMContext, user, parsed: dict) -> None:
    """Logistics (КамАЗ подвоз воды): driver + machine + work-type, NO field — becomes
    a CropWise machine task. The water goes to many fields, so we don't ask for one."""
    from catalog.cropwise_report import build_machine_task, mt_summary
    op_date = _op_date(parsed.get("date")).isoformat()
    plan = await asyncio.to_thread(
        build_machine_task, parsed.get("operation") or "подвоз",
        parsed.get("machine"), parsed.get("driver"), op_date, parsed.get("implement"))
    if not plan.get("work_type") or not plan.get("machine"):
        miss = ([] if plan.get("work_type") else ["вид работ"]) + \
               ([] if plan.get("machine") else ["машину и её номер"])
        await message.answer(
            "Не разобрал " + " и ".join(miss) + " для задания машины.\n"
            "Повторите, например: «17 июня КамАЗ 286 Двулучанский подвоз воды».")
        return
    plan["operator"] = user["full_name"]
    await state.update_data(op=plan)
    await state.set_state(OpLogForm.confirm)
    if plan.get("driver_options"):               # true active full-namesakes → ask which
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=o["name"], callback_data=f"mtdrv:{o['id']}")]
            for o in plan["driver_options"]])
        await message.answer(
            f"Несколько водителей с именем «{plan['driver_raw']}» — выберите нужного:",
            reply_markup=kb)
        return
    await _mt_proceed(message, state, plan)


async def _mt_proceed(message: Message, state: FSMContext, plan: dict) -> None:
    """Show the machine-task summary for confirmation — but for implement work (покос/
    грейдирование/…) with no implement resolved yet, ask which one first."""
    from catalog.cropwise_report import mt_summary
    if plan.get("needs_implement") and not plan.get("implement"):
        await state.update_data(op=plan, await_impl=True)
        await message.answer(
            "Какое навесное/прицепное оборудование? Напишите модель или номер "
            "(например «СД-105» или «КРН-2.1»). Если без оборудования — напишите «нет».")
        return
    await state.update_data(op=plan, await_impl=False)
    await message.answer(mt_summary(plan), reply_markup=_oplog_confirm_kb())


@router.message(OpLogForm.confirm, F.text)
async def on_mt_implement(message: Message, state: FSMContext, user) -> None:
    """Reply to the «какое оборудование?» question (machine-task confirm state)."""
    data = await state.get_data()
    reply = (message.text or "").strip()
    if not data.get("await_impl"):
        # In confirm with buttons shown but they typed text — if it's a new operation, re-route.
        if looks_like_oplog(reply):
            await state.clear()
            await _handle_op_note(message, state, user, reply)
        return
    op = data.get("op")
    if not op:
        await state.clear()
        return
    from catalog.cropwise_report import mt_summary, resolve_implement
    if reply.lower().replace("ё", "е") in ("нет", "-", "без", "не надо", "none", "no", "нету"):
        op["implement_raw"] = None
    else:
        im = await asyncio.to_thread(resolve_implement, reply)
        if not im:
            await message.answer(
                f"Не нашёл оборудование «{reply}» в CropWise. Попробуйте модель/номер ещё раз "
                "(например «СД-105»), или напишите «нет».")
            return
        op["implement"], op["implement_raw"] = {"id": im["id"], "name": im["name"]}, reply
    op["needs_implement"] = False
    await state.update_data(op=op, await_impl=False)
    await message.answer(mt_summary(op), reply_markup=_oplog_confirm_kb())


@router.callback_query(OpLogForm.confirm, F.data.startswith("mtdrv:"))
async def on_mt_driver_pick(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    await _drop_kb(callback)
    from catalog.cropwise_report import mt_summary
    op = (await state.get_data()).get("op")
    if not op or not op.get("driver_options"):
        await callback.message.answer("Сессия истекла — повторите /log.")
        await state.clear()
        return
    did = int(callback.data.split(":")[1])
    chosen = next((o for o in op["driver_options"] if o["id"] == did), None)
    if not chosen:
        await callback.message.answer("Не нашёл этого водителя, повторите.")
        return
    op["driver"], op["driver_options"] = {"id": chosen["id"], "name": chosen["name"]}, None
    await _mt_proceed(callback.message, state, op)


async def _handle_machine_batch(message: Message, state: FSMContext, user, ops: list) -> None:
    """Several logistics ops in one message → build each machine task, show a combined summary,
    create them all on one confirm. Best-effort (no per-task prompts); unparsable ones are flagged."""
    from catalog.cropwise_report import build_machine_task
    plans, lines = [], []
    for i, p in enumerate(ops, 1):
        plan = await asyncio.to_thread(
            build_machine_task, p.get("operation") or "подвоз", p.get("machine"),
            p.get("driver"), _op_date(p.get("date")).isoformat(), p.get("implement"))
        plan["operator"] = user["full_name"]
        ok = bool(plan.get("work_type") and plan.get("machine"))
        m, d = plan.get("machine"), plan.get("driver")
        impl = f" + «{plan['implement']['name']}»" if plan.get("implement") else ""
        line = (f"{'•' if ok else '⚠️'} {i}) {plan['operation']} — "
                f"{(m['name'] if m else (plan.get('machine_raw') or '?'))}{impl}, "
                f"{(d['name'] if d else 'водитель?')}")
        lines.append(line if ok else line + " — не разобрал машину/вид работ")
        if ok:
            plans.append(plan)
    head = f"🚚 Нашёл {len(ops)} заданий машин (без поля):"
    if not plans:
        await state.clear()
        await message.answer(head + "\n" + "\n".join(lines)
                             + "\n\nНи одно не распозналось — повторите по образцу "
                             "«КамАЗ 286 Двулучанский подвоз воды».")
        return
    await state.update_data(batch=plans, op=None, await_impl=False)
    await state.set_state(OpLogForm.confirm)
    foot = f"\nСоздам {len(plans)} из {len(ops)}." if len(plans) != len(ops) else ""
    await message.answer(head + "\n" + "\n".join(lines) + foot + "\n\nСоздать все?",
                         reply_markup=_oplog_confirm_kb())


async def _save_machine_batch(message: Message, batch: list) -> None:
    from catalog.cropwise_report import create_machine_task
    await message.answer(f"Создаю {len(batch)} заданий машин в CropWise…")
    ok, lines = 0, []
    for plan in batch:
        try:
            code, _ = await asyncio.to_thread(create_machine_task, plan)
        except Exception:
            logger.exception("batch machine task create failed")
            code = 0
        if code in (200, 201, 409):
            ok += 1
            tag = " (уже было)" if code == 409 else ""
            lines.append(f"✅ {plan['operation']} — {plan['machine']['name']}{tag}")
        else:
            lines.append(f"⚠️ {plan['operation']} — не принято (код {code})")
    await message.answer(f"Готово: создано {ok} из {len(batch)}.\n" + "\n".join(lines))


async def _handle_op_note(message: Message, state: FSMContext, user, note: str) -> None:
    ops = await parse_operations(note)
    if not ops:
        await message.answer(
            "Не понял. Повторите, например: «опрыскал 119 Корсаром 1.5 л/га от сорняков»."
        )
        return
    # Several operations in one message → batch them. For now: machine tasks (logistics);
    # a mix with field sprays processes the first and asks for those one at a time.
    if len(ops) > 1:
        if all(is_fieldless_op(o.get("operation") or "") for o in ops):
            await _handle_machine_batch(message, state, user, ops)
            return
        await message.answer(
            f"Вижу {len(ops)} операций. Несколько сразу пока умею только для машинных заданий "
            "(подвоз/перевоз и т.п.) — обработаю первую, полевые операции пришлите по одной.")
    parsed = ops[0]
    if is_fieldless_op(parsed.get("operation") or "") or is_fieldless_op(note):
        await _handle_machine_task(message, state, user, parsed)
        return
    cat = (parsed.get("category") or "other").lower()
    op = {
        "fields": [], "field_id": None, "field_name": None, "crop": None,
        "date": _op_date(parsed.get("date")).isoformat(), "category": cat,
        "operation": parsed.get("operation") or _OP_CAT_RU.get(cat, "операция"),
        "product": parsed.get("product"), "dv": None, "target": parsed.get("target"),
        "dose": parsed.get("dose"), "area": parsed.get("area_ha"),
        "operator": user["full_name"],
    }
    if op["product"] and cat == "protection":
        op["dv"] = await lookup_active_substance(op["product"])
    await state.update_data(op=op, farm_id=user["farm_id"], field_choices=None)
    refs = parsed.get("fields") or ([parsed["field"]] if parsed.get("field") else [])
    if refs and not await _set_fields(message, state, op, refs, user["farm_id"]):
        return   # asked отделение / not found — stays in OpLogForm.filling
    await _continue_oplog(message, state, op)


@router.message(OpLogForm.awaiting, F.voice)
async def on_oplog_voice(message: Message, state: FSMContext, user) -> None:
    file = await message.bot.get_file(message.voice.file_id)
    buffer = await message.bot.download_file(file.file_path)
    await message.answer("Распознаю…")
    try:
        note = await transcribe(buffer.read())
    except Exception:
        logger.exception("oplog voice transcription failed")
        note = ""
    if not note:
        await message.answer("Не разобрал голос — повторите ещё раз или текстом.")
        return
    await _handle_op_note(message, state, user, note)


@router.message(OpLogForm.awaiting, F.text)
async def on_oplog_text(message: Message, state: FSMContext, user) -> None:
    await _handle_op_note(message, state, user, message.text)


async def _fill_slot(message: Message, state: FSMContext, user, reply: str) -> None:
    """Apply the agronomist's answer to the slot we asked about, then continue."""
    data = await state.get_data()
    op, slot = data.get("op"), data.get("slot")
    if not op or not slot:
        await state.clear()
        await message.answer("Что-то сбилось. Начните заново: /log.")
        return
    reply = (reply or "").strip()
    if not reply:
        await message.answer(_SLOT_Q[slot])
        return
    # Escape hatch: if they typed a NEW operation instead of answering the slot — e.g. a
    # field-less «подвоз воды … КамАЗ» while we're asking for a field — re-route it as a fresh
    # op (→ machine task for logistics) instead of forcing it into the slot, which would loop
    # on «Не нашёл такое поле». Real field answers («119», «Двулучанский») aren't oplog-shaped.
    if looks_like_oplog(reply):
        await state.clear()
        await _handle_op_note(message, state, user, reply)
        return
    if slot == "field":
        choices = data.get("field_choices")
        if choices:                       # we asked which отделение — match the reply
            pick = _match_group(reply, choices)
            if not pick:
                groups = ", ".join(_group_of(c["name"]) for c in choices if _group_of(c["name"]))
                await message.answer(f"Назовите отделение: {groups}.")
                return
            _apply_field(op, pick)
            await state.update_data(field_choices=None)
        elif not await _set_field(message, state, op, reply, data.get("farm_id")):
            return                        # _set_field asked a follow-up
        await _continue_oplog(message, state, op)
        return
    elif slot == "product":
        # the answer may include the dose too («Корсар 1.5 л/га») — capture both
        m = re.search(r"[\d.,]+\s*(?:л|кг|г|ц|мл|т)\s*/\s*га", reply, re.I)
        if m and not op["dose"]:
            op["dose"] = m.group(0)
            op["product"] = reply[:m.start()].strip(" ,") or reply
        else:
            op["product"] = reply
        if op["category"] == "protection":
            op["dv"] = await lookup_active_substance(op["product"])
    elif slot == "dose":
        op["dose"] = reply
    elif slot == "crop":
        op["crop"] = reply
    await _continue_oplog(message, state, op)


@router.message(OpLogForm.filling, F.voice)
async def on_oplog_fill_voice(message: Message, state: FSMContext, user) -> None:
    file = await message.bot.get_file(message.voice.file_id)
    buffer = await message.bot.download_file(file.file_path)
    try:
        reply = await transcribe(buffer.read())
    except Exception:
        logger.exception("oplog fill voice transcription failed")
        reply = ""
    if not reply:
        await message.answer("Не разобрал голос — повторите ещё раз или текстом.")
        return
    await _fill_slot(message, state, user, reply)


@router.message(OpLogForm.filling, F.text)
async def on_oplog_fill_text(message: Message, state: FSMContext, user) -> None:
    await _fill_slot(message, state, user, message.text)


@router.callback_query(OpLogForm.confirm, F.data == "oplog:save")
async def on_oplog_save(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    await _drop_kb(callback)
    data = await state.get_data()
    op, batch = data.get("op"), data.get("batch")
    await state.clear()
    if batch:                                       # several machine tasks at once
        await _save_machine_batch(callback.message, batch)
        return
    if not op:
        await callback.message.answer("Нечего сохранять.")
        return
    if op.get("kind") == "machine_task":            # logistics: no field, → CropWise machine task
        from catalog.cropwise_report import create_machine_task
        await callback.message.answer("Создаю задание машины в CropWise…")
        try:
            code, detail = await asyncio.to_thread(create_machine_task, op)
        except Exception:
            logger.exception("machine task create failed")
            code, detail = 0, "ошибка"
        if code in (200, 201):
            extra = " (добавил оборудование)" if detail == "implement_added" else ""
            await callback.message.answer(
                f"✅ Задание машины создано{extra}: «{op['work_type']['name']}», "
                f"{op['machine']['name']}. Проверьте в CropWise.")
        elif code == 409:
            await callback.message.answer(
                f"✅ Это задание уже было создано ранее — оно есть в CropWise: "
                f"«{op['work_type']['name']}», {op['machine']['name']}.")
        else:
            logger.warning("machine task rejected (code %s): %s", code, detail)
            await callback.message.answer(
                f"⚠️ CropWise не принял задание машины (код {code}). Запись не создана.\n"
                f"Причина: {(detail or '')[:250]}")
        return
    fields = op.get("fields") or ([_field_entry_from_op(op)] if op.get("field_id") else [])
    if not fields:
        await callback.message.answer("Нечего сохранять.")
        return
    await callback.message.answer("Сохраняю…")
    from catalog.cropwise_push import push_treatment
    saved, dup, lines = 0, 0, []
    # One field_treatments row + one CropWise push PER field (a multi-field note like
    # «опрыскал поля 262, 252, 251 …» fans out to one operation each).
    for f in fields:
        tid = await insert_bot_treatment(
            field_id=f["id"], field_name=f["name"],
            treatment_date=date.fromisoformat(op["date"]), crop=f.get("crop"),
            operation=op["operation"], op_category=op["category"], product=op["product"],
            active_substance=op["dv"], target=op["target"], dose=op["dose"],
            area_ha=f.get("area"), operator=op["operator"],
        )
        if not tid:
            dup += 1
            lines.append(f"• {f['name']}: дубликат, пропущено")
            continue
        saved += 1
        parsed_like = {"category": op["category"], "operation": op["operation"],
                       "product": op["product"], "dose": op["dose"],
                       "area_ha": f.get("area"), "date": op["date"]}
        try:
            ok, _ = await asyncio.to_thread(push_treatment, f["name"], f.get("area"), parsed_like)
        except Exception:
            logger.exception("cropwise push failed")
            ok = False
        if ok:
            await mark_treatment_synced(tid)
            lines.append(f"• {f['name']}: ✅ история + CropWise")
        else:
            lines.append(f"• {f['name']}: ✅ история, ⚠️ CropWise не принял")
    head = (f"Готово: записано {saved} из {len(fields)}"
            + (f", дубликатов {dup}" if dup else "") + ".")
    await callback.message.answer(head + "\n" + "\n".join(lines)
                                  + ("\n\nПроверьте в CropWise." if saved else ""))


@router.callback_query(OpLogForm.confirm, F.data == "oplog:cancel")
async def on_oplog_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    await _drop_kb(callback)
    await state.clear()
    await callback.message.answer("Отменено.")


# Button-only steps (confirm / pickers) have no text handler — so stray text used
# to vanish silently and leave the user stuck (their «поле …» alias wouldn't fire).
# Nudge them to the buttons or /cancel instead of swallowing it.
@router.message(
    StateFilter(OpLogForm.confirm, PhotoForm.field, PhotoForm.category,
                PhotoForm.subcategory, PhotoForm.treatment),
    F.text,
)
async def on_stray_text_in_button_step(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Сейчас нужно выбрать вариант кнопкой выше 👆\n"
        "Если хотите выйти и начать заново — отправьте /cancel.")


# ---------- «Задания машин»: paste a field report → create CropWise operations ----
# Евгения (operator) pastes a report from Max; the bot parses it, previews the plan,
# and on ✅ creates one agro-operation per field (tank mix + work-type + driver).
def _looks_like_report(message: Message) -> bool:
    lines = [l for l in (message.text or "").splitlines() if l.strip()]
    if len(lines) < 3:
        return False
    field_re = re.compile(r"^\s*\d+[а-яa-z]?\s*/\s*\d+\s*$", re.I)
    return any(field_re.match(l) for l in lines) or any(re.match(r"^\s*#\s*\d+", l) for l in lines)


@router.message(StateFilter(None), F.text, _looks_like_report)
async def on_report_paste(message: Message, state: FSMContext, user) -> None:
    if user["role"] not in ("admin", "chief_agronomist", "annotator"):
        return  # only operators turn reports into CropWise tasks
    await message.answer("Разбираю отчёт…")
    from catalog.cropwise_report import build_plan, plan_summary
    try:
        plan, err = await build_plan(message.text)
    except Exception:
        logger.exception("report parse failed")
        plan, err = None, "ошибка разбора"
    if not plan:
        await message.answer(f"Не удалось разобрать отчёт ({err}). Проверьте формат.")
        return
    await state.update_data(report_plan=plan)
    await state.set_state(CAReport.confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Создать в CropWise", callback_data="rep:create"),
        InlineKeyboardButton(text="✗ Отмена", callback_data="rep:cancel")]])
    await message.answer(plan_summary(plan), reply_markup=kb)


@router.callback_query(CAReport.confirm, F.data == "rep:create")
async def on_report_create(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    await _drop_kb(callback)
    plan = (await state.get_data()).get("report_plan")
    await state.clear()
    if not plan:
        await callback.message.answer("Нечего создавать.")
        return
    await callback.message.answer("Создаю операции в CropWise…")
    from catalog.cropwise_report import create_ops
    try:
        results = await asyncio.to_thread(create_ops, plan)
    except Exception:
        logger.exception("report create failed")
        await callback.message.answer("⚠️ Ошибка при создании операций в CropWise.")
        return
    created = sum(1 for r in results if r.get("ok") and not r.get("already"))
    already = sum(1 for r in results if r.get("already"))
    failed = [r for r in results if not r.get("ok")]

    def _line(r):
        if r.get("already"):
            return f"↺ поле {r['field']} — уже было создано ранее"
        if r.get("ok"):
            return f"✓ поле {r['field']}"
        return (f"✗ поле {r['field']} — "
                + str(r.get("msg") or r.get("detail") or ("код " + str(r.get("code")))))

    head = f"Готово: создано {created}"
    if already:
        head += f", уже было ранее {already}"
    if failed:
        head += f", не удалось {len(failed)}"
    head += f" (всего {len(results)})."
    await callback.message.answer(head + "\n" + "\n".join(_line(r) for r in results)
                                  + "\n\nПроверьте в CropWise.")


@router.callback_query(CAReport.confirm, F.data == "rep:cancel")
async def on_report_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    await _drop_kb(callback)
    await state.clear()
    await callback.message.answer("Отменено.")


# ---------- free-text operation log: «опрыскал поле 119 …» → the REAL save flow ----
# The bot guide tells agronomists to just type the operation. This routes such a
# statement into parse → confirm card (✓) → save + CropWise, instead of letting it
# fall to the assistant below (which only DESCRIBES logging and never saves — the bug
# Евгения hit: bot "accepted" the spray but it never reached CropWise). Questions
# («чем обработать сою?») don't match and still go to the assistant.
def _oplog_filter(message: Message) -> bool:
    return looks_like_oplog(message.text or "")


@router.message(StateFilter(None), F.text, _oplog_filter)
async def on_oplog_freetext(message: Message, state: FSMContext, user) -> None:
    await _handle_op_note(message, state, user, message.text)


# ---------- conversational Q&A: free-text question → grounded colloquial answer ----
_THIS_FIELD_RE = re.compile(r"эт(?:о|ом|ого|ой)\s+пол|на этом пол|здесь|тут|где я", re.I)
_FIELD_REF_RE = re.compile(r"пол[еяю]\s*№?\s*(\d+[а-я]?(?:\s*/\s*\d+)?)", re.I)


def _extract_field_ref(text: str):
    t = (text or "").replace("ё", "е")
    if _THIS_FIELD_RE.search(t):
        return "__last__"
    m = _FIELD_REF_RE.search(t)
    return re.sub(r"\s+", "", m.group(1)) if m else None


@router.message(StateFilter(None), F.location)
async def on_location(message: Message, state: FSMContext, user) -> None:
    loc = message.location
    field = await field_at_point(loc.latitude, loc.longitude, user["farm_id"])
    if not field:
        await message.answer("Не нашёл поле по этим координатам. Назовите поле номером, например «119».")
        return
    await state.update_data(last_field_id=field["id"], last_field_name=field["name"])
    await message.answer(
        f"📍 Вы на поле {field['name']}" + (f" · {field['crop']}" if field["crop"] else "")
        + ".\nСпросите что-нибудь о нём — например «какая обработка была недавно?».")


async def _chat_history_get(tg_id) -> str | None:
    """Recent assistant Q&A for this user (30-min window) so follow-ups like «предложите
    варианты» keep context. Best-effort — None on any Redis hiccup."""
    try:
        return (await _web_redis.get(f"flagleaf:chat:{tg_id}")) or None
    except Exception:
        return None


async def _chat_history_push(tg_id, q: str, a: str) -> None:
    try:
        prev = (await _web_redis.get(f"flagleaf:chat:{tg_id}")) or ""
        turns = prev.split("\n\n") if prev else []
        turns.append(f"Пользователь: {q[:1500]}\nАссистент: {a[:1500]}")
        await _web_redis.set(f"flagleaf:chat:{tg_id}", "\n\n".join(turns[-4:]), ex=1800)
    except Exception:
        pass


@router.message(StateFilter(None), F.text)   # LAST text handler — free-text → a question
async def on_question(message: Message, state: FSMContext, user) -> None:
    q = (message.text or "").strip()
    ref = _extract_field_ref(q)
    context = None
    if ref == "__last__":
        fn = (await state.get_data()).get("last_field_name")
        if not fn:
            await message.answer("О каком поле речь? Назовите номер (например «119») или "
                                 "пришлите геопозицию (📎 → Геопозиция), и я определю поле сам.")
            return
        context = await field_card_text(fn, user["farm_id"])
    elif ref:
        field = await resolve_field(ref, user["farm_id"])
        if field:
            await state.update_data(last_field_id=field["id"], last_field_name=field["name"])
            context = await field_card_text(field["name"], user["farm_id"])
    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass
    hist = await _chat_history_get(message.from_user.id)
    ans = await agro_answer(q, context, hist)
    await message.answer(ans or "Не понял вопрос — переформулируйте, пожалуйста.")
    if ans:
        await _chat_history_push(message.from_user.id, q, ans)


# ---------- contact / phone (onboarding fallback). Keep LAST so it never
# ---------- swallows messages that belong to the photo flow above. ----------

@router.message(F.contact)
async def on_contact(message: Message, user) -> None:
    await set_user_phone(message.from_user.id, message.contact.phone_number)
    await message.answer("Готово, номер сохранён.", reply_markup=ReplyKeyboardRemove())
    await _show_fields(message, user["farm_id"])


@router.message(F.text)
async def on_text(message: Message, user) -> None:
    if user["phone"]:
        return
    digits = re.sub(r"\D", "", message.text)
    if len(digits) < 10:
        await message.answer(
            "Не похоже на номер телефона. Нажмите кнопку «Поделиться номером» "
            "или введите номер в формате +7XXXXXXXXXX."
        )
        return
    await set_user_phone(message.from_user.id, message.text.strip())
    await message.answer("Готово, номер сохранён.", reply_markup=ReplyKeyboardRemove())
    await _show_fields(message, user["farm_id"])

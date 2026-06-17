import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from uuid import uuid4

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
    deactivate_user,
    delete_submission,
    field_card_text,
    find_duplicate_submission,
    find_fields_by_number,
    get_all_recent_submissions,
    get_all_species,
    get_chief_agronomists,
    get_pending_submission,
    get_submission_image_url,
    get_submission_review,
    get_field_polygons,
    get_pilot_fields,
    get_recent_treatments,
    get_species,
    resolve_field_id,
    get_team_week_counts,
    get_top_species,
    find_similar_treatment,
    get_user_history,
    get_user_stats,
    insert_bot_treatment,
    lookup_active_substance,
    ndvi_scan,
    resolve_field,
    set_user_phone,
    update_submission,
)
from bot import fieldmap
from bot.ndvi_watch import format_digest
from bot.parse_op import parse_operation
from bot.states import CAReview, OpLogForm, PhotoForm, ProblemForm
from bot.storage import delete_object, download_bytes, upload_bytes
from bot.weed_suggest import suggest_species
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
    # Off-pilot training photos (margins, other parcels of the farm): valuable
    # for the CV model, but kept out of the 3 pilot fields' records so the
    # day-90 economic proof + per-field weed maps stay clean.
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
    fields = await get_pilot_fields(farm_id)
    if not fields:
        await message.answer(
            "Поля ещё не настроены. Их добавит администратор на следующем шаге."
        )
        return

    lines = ["Ваши пилотные поля:"]
    for f in fields:
        meta_parts = []
        if f["crop"]:
            meta_parts.append(f["crop"])
        if f["area_ha"] is not None:
            meta_parts.append(f"{float(f['area_ha']):g} га")
        meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
        lines.append(f"• {f['name']}{meta}")
    lines.append("\nГотовы начать? Просто отправляйте фото.")
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
        f"• Всего сохранено: {int(s['total'])}"
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

    fields = await get_pilot_fields(user["farm_id"])
    if not fields:
        await message.answer("Поля не настроены — обратитесь к администратору.")
        await state.clear()
        return
    await message.answer("На каком поле?", reply_markup=_fields_kb(fields))


@router.message(F.photo)
async def on_photo(message: Message, state: FSMContext, user) -> None:
    """Photo sent via Telegram's camera/gallery button. Telegram compresses
    to ~1280–2560 px on the long edge; for full original resolution the
    sender should use paperclip → File (see on_photo_document below)."""
    photo = message.photo[-1]  # largest variant Telegram offers
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
        await callback.message.answer("Введите название вида (или /skip):")
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
    # Junior agronomists' photos go to the chief agronomist for review first;
    # chief agronomist and admins post straight to the labeling pipeline.
    if user["role"] == "agronomist":
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
        await update_submission(sid, status="ready_for_labeling")
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
    if action == "ok":
        await _ack(callback, "Отправлено на разметку ✓")
        await _drop_kb(callback)
        await update_submission(sid, status="ready_for_labeling")
        sub = await get_submission_review(sid)
        await callback.message.answer("✅ Отправлено на разметку.")
        if sub and sub["submitter_tg"]:
            try:
                await callback.bot.send_message(
                    sub["submitter_tg"], "✅ Ваше фото проверено старшим агрономом и "
                    "отправлено на разметку. Спасибо!")
            except Exception:
                logger.exception("notify submitter (approve) failed")
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
    # The correction itself finalizes the photo — straight to the annotator, no
    # extra confirmation. The junior is only notified.
    await update_submission(sid, status="ready_for_labeling")
    await state.clear()
    if sub and sub["submitter_tg"]:
        try:
            await message.bot.send_message(
                sub["submitter_tg"],
                f"✏️ Старший агроном исправил {_ATTR_RU[attr]} в вашем фото: "
                f"«{old or '—'}» → «{newval}». Фото отправлено на разметку.")
        except Exception:
            logger.exception("notify submitter (correction) failed")
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
# confirmation, and on ✓ it lands in field_treatments (source='bot'). The daily
# nudge (bot/op_nudge.py) drops the agronomist straight into this flow.

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
    lines = ["Записать операцию?",
             f"📍 {op['field_name']}" + (f" · {op['crop']}" if op["crop"] else ""),
             f"🛠 {op['operation']}"]
    if op["product"]:
        lines.append(f"📦 {op['product']}" + (f" ({op['dv']})" if op["dv"] else ""))
    bits = [b for b in (op["dose"], op["target"]) if b]
    if bits:
        lines.append("• " + " · ".join(bits))
    if op["area"]:
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


def _apply_field(op: dict, field) -> None:
    op["field_id"] = field["id"]
    op["field_name"] = field["name"]
    op["crop"] = field["crop"]
    if op["area"] is None and field["area_ha"] is not None:
        op["area"] = float(field["area_ha"])


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
    summary = _op_summary(op)
    dups = await find_similar_treatment(
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


async def _handle_op_note(message: Message, state: FSMContext, user, note: str) -> None:
    parsed = await parse_operation(note)
    if not parsed:
        await message.answer(
            "Не понял. Повторите, например: «опрыскал 119 Корсаром 1.5 л/га от сорняков»."
        )
        return
    cat = (parsed.get("category") or "other").lower()
    op = {
        "field_id": None, "field_name": None, "crop": None,
        "date": _op_date(parsed.get("date")).isoformat(), "category": cat,
        "operation": parsed.get("operation") or _OP_CAT_RU.get(cat, "операция"),
        "product": parsed.get("product"), "dv": None, "target": parsed.get("target"),
        "dose": parsed.get("dose"), "area": parsed.get("area_ha"),
        "operator": user["full_name"],
    }
    if op["product"] and cat == "protection":
        op["dv"] = await lookup_active_substance(op["product"])
    await state.update_data(op=op, farm_id=user["farm_id"], field_choices=None)
    fq = parsed.get("field")
    if fq and not await _set_field(message, state, op, str(fq), user["farm_id"]):
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
    op = (await state.get_data()).get("op")
    await state.clear()
    if not op:
        await callback.message.answer("Нечего сохранять.")
        return
    inserted = await insert_bot_treatment(
        field_id=op["field_id"], field_name=op["field_name"],
        treatment_date=date.fromisoformat(op["date"]), crop=op["crop"],
        operation=op["operation"], op_category=op["category"], product=op["product"],
        active_substance=op["dv"], target=op["target"], dose=op["dose"],
        area_ha=op["area"], operator=op["operator"],
    )
    if not inserted:
        await callback.message.answer("ℹ️ Такая операция уже была записана — дубликат пропущен.")
        return
    await callback.message.answer("✅ Записано в историю поля. Отправляю в CropWise…")
    # Mirror the operation into CropWise (confirm-before-push: this IS the confirm).
    # Sync requests under the hood → run off the event loop. Never blocks the save:
    # the history row is already in; a CropWise hiccup is just a warning.
    parsed_like = {
        "category": op["category"], "operation": op["operation"],
        "product": op["product"], "dose": op["dose"],
        "area_ha": op["area"], "date": op["date"],
    }
    try:
        from catalog.cropwise_push import push_treatment
        ok, msg = await asyncio.to_thread(
            push_treatment, op["field_name"], op["area"], parsed_like)
    except Exception:
        logger.exception("cropwise push failed")
        ok, msg = False, "не удалось отправить в CropWise (в истории поля запись сохранена)"
    await callback.message.answer(("📤 " if ok else "⚠️ ") + msg)


@router.callback_query(OpLogForm.confirm, F.data == "oplog:cancel")
async def on_oplog_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    await _drop_kb(callback)
    await state.clear()
    await callback.message.answer("Отменено.")


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

import hashlib
import logging
import re
from datetime import date
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
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
    get_pending_submission,
    get_pilot_fields,
    get_recent_treatments,
    get_species,
    get_team_week_counts,
    get_top_species,
    get_user_history,
    get_user_stats,
    set_user_phone,
    update_submission,
)
from bot.states import PhotoForm, ProblemForm
from bot.storage import delete_object, upload_bytes
from bot.transcribe import transcribe
from bot.translate_llm import translate_ru_to_en
from bot.taxonomy import DISEASES, DISEASE_RU_BY_CODE, PESTS_PICKER, PEST_RU_BY_CODE

router = Router()
logger = logging.getLogger("bot.handlers")


async def _ack(callback: CallbackQuery) -> None:
    """Acknowledge a callback, but never let it abort the handler. Through the
    Telegram relay an update can arrive late and the callback go stale; a raw
    `callback.answer()` would then throw and we'd lose the user's tap (the
    field/category/species selection). Swallowing it keeps the actual DB write
    running — the next prompt is a fresh message and reaches the user anyway."""
    try:
        await callback.answer()
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
    rows = [[InlineKeyboardButton(text=f["name"], callback_data=f"field:{f['id']}")] for f in fields]
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
    await message.answer(await field_card_text(q, user["farm_id"]))


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

    # "Другой" — branch to free-text input.
    if value == "other":
        await state.set_state(PhotoForm.subcategory_other)
        await callback.message.answer("Введите название вида (или /skip):")
        return

    data = await state.get_data()
    if value != "skip":
        species = await get_species(int(value))
        if species:
            await update_submission(data["submission_id"], subcategory=species["latin_name"])
    await state.set_state(PhotoForm.comment)
    await callback.message.answer("Комментарий? Текстом или голосом. Или /skip.")


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


async def _finalize(message: Message, state: FSMContext, user) -> None:
    data = await state.get_data()
    await update_submission(data["submission_id"], status="ready_for_labeling")
    await state.clear()
    today, week = await count_user_submissions(user["id"])
    await message.answer(
        f"Записал. Сохранено ✓\nЗа сегодня: {today}. За неделю: {week}."
    )


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


# ---------- treatment link: tie the photo to a recent field operation ----------
# The photo is already saved before these run (_ask_treatment_or_finalize
# finalizes first), so they only attach the optional link and clear state.

@router.callback_query(PhotoForm.treatment, F.data.startswith("trt:"))
async def on_treatment(callback: CallbackQuery, state: FSMContext) -> None:
    await _ack(callback)
    value = callback.data.split(":", 1)[1]

    if value == "skip":
        await state.clear()
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


@router.message(PhotoForm.treatment_note, Command("skip"))
async def on_skip_treatment_note(message: Message, state: FSMContext) -> None:
    await state.clear()


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

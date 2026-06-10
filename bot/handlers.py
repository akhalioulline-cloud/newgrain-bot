import logging
import re
from datetime import date
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
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
    get_all_recent_submissions,
    get_pending_submission,
    get_pilot_fields,
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
from bot.transcribe import transcribe, translate_en

router = Router()
logger = logging.getLogger("bot.handlers")

CATEGORIES = [
    ("Сорняк", "weed"),
    ("Болезнь", "disease"),
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
    rows.append([InlineKeyboardButton(text="Другое поле / вне пилота", callback_data="field:other")])
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
    "/finish — закончить незавершённое фото\n"
    "/problem — сообщить о проблеме или задать вопрос\n"
    "/cancel — отменить текущий шаг\n"
    "/help — это сообщение"
)

ADMIN_HELP = (
    "\n\nКоманды администратора:\n"
    "/all — последние загрузки всех агрономов\n"
    "/adduser <id> <имя> — добавить агронома\n"
    "/removeuser <id> — убрать доступ"
)


@router.message(Command("help"))
async def cmd_help(message: Message, user) -> None:
    await message.answer(HELP_TEXT + (ADMIN_HELP if _is_admin(user) else ""))


@router.message(Command("fields"))
async def cmd_fields(message: Message, user) -> None:
    await _show_fields(message, user["farm_id"])


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

    await state.update_data(submission_id=str(pending["id"]))
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
    else:
        # Category set (and subcategory if weed) — only the comment remains.
        await state.set_state(PhotoForm.comment)
        await message.answer(f"{intro} Комментарий? Текстом или голосом. Или /skip.")


# ---------- /adduser: admin whitelists a new agronomist ----------

def _is_admin(user) -> bool:
    return user["role"] == "admin" or user["tg_user_id"] in settings.admin_ids


@router.message(Command("all"))
async def cmd_all(message: Message, user) -> None:
    """Admin-only: recent uploads from EVERY agronomist. /history and /stats are
    per-user (each person sees only their own), so this is the admin's window
    into what the rest of the team has sent."""
    if not _is_admin(user):
        await message.answer("Эта команда доступна только администратору.")
        return

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


@router.callback_query(PhotoForm.field, F.data.startswith("field:"))
async def on_field(callback: CallbackQuery, state: FSMContext, user) -> None:
    await callback.answer()
    token = callback.data.split(":")[1]
    # "other" = off-pilot training photo: field_id stays NULL so it never
    # pollutes the 3 pilot fields' per-field records, but still flows through
    # labeling as training data.
    if token == "other":
        field_id = None
        path_seg = "other"
    else:
        field_id = int(token)
        path_seg = str(field_id)
    data = await state.get_data()

    file = await callback.bot.get_file(data["file_id"])
    buffer = await callback.bot.download_file(file.file_path)
    submission_id = str(uuid4())
    mime = data.get("mime", "image/jpeg")
    key = f"raw/{user['farm_id']}/{path_seg}/{date.today():%Y-%m-%d}/{submission_id}.{_ext_for_mime(mime)}"
    image_url = await upload_bytes(key, buffer.read(), mime)

    await create_submission(
        submission_id, user["id"], field_id, image_url, data.get("width"), data.get("height")
    )
    await state.update_data(submission_id=submission_id)
    await state.set_state(PhotoForm.category)
    await callback.message.answer("Что на фото?", reply_markup=_category_kb())


@router.callback_query(PhotoForm.category, F.data.startswith("cat:"))
async def on_category(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    code = callback.data.split(":")[1]
    data = await state.get_data()
    await update_submission(data["submission_id"], category=code)

    if code == "weed":
        species = await get_top_species()
        await state.set_state(PhotoForm.subcategory)
        await callback.message.answer(
            "Какой вид? (можно пропустить)", reply_markup=_species_kb(species)
        )
    else:
        await state.set_state(PhotoForm.comment)
        await callback.message.answer("Комментарий? Текстом или голосом. Или /skip.")


@router.callback_query(PhotoForm.subcategory, F.data.startswith("sub:"))
async def on_subcategory(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
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


@router.message(PhotoForm.comment, Command("skip"))
async def on_skip_comment(message: Message, state: FSMContext, user) -> None:
    await _finalize(message, state, user)


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
        # English translation for the (possibly non-Russian-speaking) annotator.
        try:
            english = await translate_en(audio)
        except Exception:
            logger.exception("voice translation failed for %s", data["submission_id"])
            english = ""
        if english:
            await update_submission(data["submission_id"], comment_voice_text_en=english)
    else:
        await message.answer("Не удалось распознать речь — голосовое сохранил как есть.")

    await _finalize(message, state, user)


@router.message(PhotoForm.comment, F.text)
async def on_text_comment(message: Message, state: FSMContext, user) -> None:
    await update_submission((await state.get_data())["submission_id"], comment_text=message.text)
    await _finalize(message, state, user)


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

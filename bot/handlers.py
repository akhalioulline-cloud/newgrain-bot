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
    get_pilot_fields,
    get_species,
    get_top_species,
    get_user_history,
    get_user_stats,
    set_user_phone,
    update_submission,
)
from bot.states import PhotoForm, ProblemForm
from bot.storage import upload_bytes
from bot.transcribe import transcribe

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


# ---------- keyboards ----------

def _fields_kb(fields) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f["name"], callback_data=f"field:{f['id']}")] for f in fields]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _category_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f"cat:{code}")] for label, code in CATEGORIES]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _species_kb(species) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=s["russian_name"], callback_data=f"sub:{s['id']}")]
        for s in species
    ]
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
    await state.clear()
    await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())


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
    "/problem — сообщить о проблеме или задать вопрос\n"
    "/cancel — отменить текущий шаг\n"
    "/help — это сообщение"
)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


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


# ---------- /adduser: admin whitelists a new agronomist ----------

def _is_admin(user) -> bool:
    return user["role"] == "admin" or user["tg_user_id"] in settings.admin_ids


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

@router.message(F.photo)
async def on_photo(message: Message, state: FSMContext, user) -> None:
    photo = message.photo[-1]  # largest size
    await state.set_state(PhotoForm.field)
    await state.update_data(file_id=photo.file_id, width=photo.width, height=photo.height)
    await message.answer("Принял фото. Пара уточнений:")

    fields = await get_pilot_fields(user["farm_id"])
    if not fields:
        await message.answer("Поля не настроены — обратитесь к администратору.")
        await state.clear()
        return
    await message.answer("На каком поле?", reply_markup=_fields_kb(fields))


@router.callback_query(PhotoForm.field, F.data.startswith("field:"))
async def on_field(callback: CallbackQuery, state: FSMContext, user) -> None:
    await callback.answer()
    field_id = int(callback.data.split(":")[1])
    data = await state.get_data()

    file = await callback.bot.get_file(data["file_id"])
    buffer = await callback.bot.download_file(file.file_path)
    submission_id = str(uuid4())
    key = f"raw/{user['farm_id']}/{field_id}/{date.today():%Y-%m-%d}/{submission_id}.jpg"
    image_url = await upload_bytes(key, buffer.read(), "image/jpeg")

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
    data = await state.get_data()
    if value != "skip":
        species = await get_species(int(value))
        if species:
            await update_submission(data["submission_id"], subcategory=species["latin_name"])
    await state.set_state(PhotoForm.comment)
    await callback.message.answer("Комментарий? Текстом или голосом. Или /skip.")


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

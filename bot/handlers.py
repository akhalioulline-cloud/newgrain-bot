import re
from datetime import date
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
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

from bot.db import (
    count_user_submissions,
    create_submission,
    get_pilot_fields,
    get_species,
    get_top_species,
    set_user_phone,
    update_submission,
)
from bot.states import PhotoForm
from bot.storage import upload_bytes

router = Router()

CATEGORIES = [
    ("Сорняк", "weed"),
    ("Болезнь", "disease"),
    ("Стресс", "stress"),
    ("Контроль", "control"),
    ("Результат обработки", "treatment_result"),
]


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
    key = f"voice/{date.today():%Y-%m-%d}/{data['submission_id']}.ogg"
    voice_url = await upload_bytes(key, buffer.read(), "audio/ogg")
    await update_submission(data["submission_id"], comment_voice_url=voice_url)
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

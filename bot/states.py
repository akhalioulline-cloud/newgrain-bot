from aiogram.fsm.state import State, StatesGroup


class PhotoForm(StatesGroup):
    field = State()
    category = State()
    subcategory = State()
    comment = State()

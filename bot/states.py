from aiogram.fsm.state import State, StatesGroup


class PhotoForm(StatesGroup):
    field = State()
    category = State()
    subcategory = State()
    subcategory_other = State()  # waiting for free-text species name
    comment = State()


class ProblemForm(StatesGroup):
    waiting = State()

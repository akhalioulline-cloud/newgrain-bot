from aiogram.fsm.state import State, StatesGroup


class PhotoForm(StatesGroup):
    field = State()
    category = State()
    subcategory = State()
    subcategory_other = State()  # waiting for free-text species name
    comment = State()
    treatment = State()          # picking a recent field operation this photo relates to
    treatment_note = State()     # waiting for free-text/voice "Другое" treatment


class ProblemForm(StatesGroup):
    waiting = State()

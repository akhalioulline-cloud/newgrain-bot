from aiogram.fsm.state import State, StatesGroup


class PhotoForm(StatesGroup):
    field = State()
    field_number = State()       # waiting for a typed field number (non-pilot fields)
    category = State()
    subcategory = State()
    subcategory_other = State()  # waiting for free-text species name
    comment = State()
    treatment = State()          # picking a recent field operation this photo relates to
    treatment_note = State()     # waiting for free-text/voice "Другое" treatment


class ProblemForm(StatesGroup):
    waiting = State()


class OpLogForm(StatesGroup):
    awaiting = State()   # waiting for a free-form/voice operation note
    confirm = State()    # parsed op shown, waiting for ✓/✗

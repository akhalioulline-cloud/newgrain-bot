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


class CAReview(StatesGroup):
    editing = State()    # chief agronomist typing a corrected attribute value


class ProblemForm(StatesGroup):
    waiting = State()


class OpLogForm(StatesGroup):
    awaiting = State()   # waiting for a free-form/voice operation note
    filling = State()    # asking back for a missing slot (field/product/dose/crop)
    confirm = State()    # parsed op shown, waiting for ✓/✗

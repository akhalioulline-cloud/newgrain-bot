"""Tell apart a free-text message that LOGS a completed field operation
("опрыскал поле 119 Корсаром 1.5 л/га", "17 июня КамАЗ 286 подвозил воду на поле
Двулучанский") from a QUESTION to the assistant ("чем обработать сою от злаковых?").

Why it matters: the bot guide tells agronomists to just TYPE the operation. Without
this router that free text fell through to the conversational assistant, which only
*described* how to log and produced a fake "запись принята" reply — nothing was ever
parsed or saved (the bug: bot "accepted" it but it never reached CropWise). A match
here sends the text into the real log flow instead.

Stdlib-only so it's unit-testable without the aiogram/bot stack.
"""
import re

# Past-tense action verbs + operation nouns (stems; ё is normalised to е before match).
_VERB_RE = re.compile(
    r"опрыск|опрысн|обработа|обработк|внес|разброс|разбрас|подкорм|посея|посев|посади|засея|"
    r"дисков|культива|боронов|боронил|прикат|вспах|пахал|подвоз|подвез|скос|косил|убрал|убира|"
    r"уборк|намолот|обмолот|полил|пролил|произвед|произвел",
    re.I,
)

# A leading question word (or a '?' anywhere) means it's a question, not a log entry.
# Anchored at the start so an incidental "как обычно" mid-sentence doesn't misfire.
_Q_RE = re.compile(
    r"\?|^\s*(чем|как|какой|кака\w*|каки\w*|каким|когда|что|чего|почему|зачем|нужно|можно|"
    r"надо|стоит|посовету\w*|подскаж\w*|сколько|где|кто)\b",
    re.I,
)

# Some concrete anchor — a field word or any number (field #, dose, or date).
_ANCHOR_RE = re.compile(r"пол[еяю]|участк|\d")

# Field-less machine work — operations NOT tied to a crop field: transport (подвоз/закачка
# воды, перевозка, доставка) AND territory/road work (покос травы, обкос, грейдирование/
# чистка/подсыпка дорог). These become a CropWise MACHINE TASK (machine + work-type +
# driver, no field), so the log flow must NOT demand a field number (Евгения's request).
# The router below treats them as log triggers too — else «покос травы …» / «закачка воды …»
# would fall through to the assistant (which can't log them).
_FIELDLESS_RE = re.compile(
    r"подвоз|подвез|перевоз|перевез|достав|транспорт|закачк|"
    r"покос|обкос|кошен|скашив|грейдир|дорог|подсыпк",
    re.I,
)


def is_fieldless_op(operation_text: str) -> bool:
    """True if the operation isn't tied to a field (→ CropWise machine task, no field)."""
    return bool(_FIELDLESS_RE.search((operation_text or "").replace("ё", "е")))


def looks_like_oplog(text: str) -> bool:
    """True if `text` reads as an agronomist logging a done operation (→ real log
    flow), False if it's a question or anything else (→ conversational assistant).
    Field-less verbs (подвоз/покос/грейдирование/…) count too — they route on to the
    machine-task flow."""
    t = (text or "").replace("ё", "е")
    if _Q_RE.search(t):
        return False
    if not (_VERB_RE.search(t) or _FIELDLESS_RE.search(t)):
        return False
    return bool(_ANCHOR_RE.search(t))

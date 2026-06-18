"""The free-text router that decides: log an operation vs. ask the assistant.
Regression guard for the bug where typed operations were faked by the chatbot and
never saved. Uses Евгения's real phrasings from the field test.
"""
from bot.oplog_match import is_logistics_op, looks_like_oplog


# Real operation statements → must enter the log flow (True)
def test_spray_statement_is_a_log():
    assert looks_like_oplog(
        "опрыскал поля 262, 252, 251 препаратом Инквант Супер с нормой 1 л/га "
        "на самоходке 6448 Яровым 17 июня")


def test_kamaz_haul_is_a_log():
    assert looks_like_oplog("17 июня КамАЗ 286 подвозил воду на поле Двулучанский")


def test_canonical_guide_example_is_a_log():
    assert looks_like_oplog("опрыскал поле 119 Корсаром 1.5 л/га от сорняков")


def test_various_operations_are_logs():
    assert looks_like_oplog("внёс аммиачную селитру 100 кг/га на поле 121")
    assert looks_like_oplog("посеял сою на поле 140 17 июня")
    assert looks_like_oplog("забороновал поле 76")


# Real questions → must go to the assistant (False)
def test_product_question_is_not_a_log():
    assert not looks_like_oplog("чем обработать сою от злаковых сорняков?")


def test_history_question_is_not_a_log():
    assert not looks_like_oplog("какая обработка была недавно на поле 119?")
    assert not looks_like_oplog("когда последний раз опрыскивали поле 76?")


def test_plain_field_query_is_not_a_log():
    assert not looks_like_oplog("поле 119")
    assert not looks_like_oplog("что на этом поле?")


def test_empty_is_not_a_log():
    assert not looks_like_oplog("")
    assert not looks_like_oplog(None)


def test_verb_without_anchor_is_not_a_log():
    # an operation word but no field/number to act on → not a log entry
    assert not looks_like_oplog("опрыскивание прошло хорошо")


# Logistics detection → machine task (no field) vs ordinary field operation
def test_logistics_ops_detected():
    assert is_logistics_op("подвоз воды")
    assert is_logistics_op("перевозка зерна")
    assert is_logistics_op("доставка семян")


def test_field_ops_are_not_logistics():
    assert not is_logistics_op("опрыскивание")
    assert not is_logistics_op("сев сои")
    assert not is_logistics_op("")

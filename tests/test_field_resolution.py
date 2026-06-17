"""Field-number matching — the logic behind «поле 47». Regression guard for the
47→147 bug: a numeric query must never match inside a longer field number.
"""
from bot.db import _field_number, _pick_field

FIELDS = [
    {"id": 1, "name": "Поле 147 · Красное"},
    {"id": 2, "name": "Поле 47 · Тишанка"},
    {"id": 3, "name": "Поле 76/108"},
    {"id": 4, "name": "Поле 119"},
    {"id": 5, "name": "Поле 47 · Хлевище"},   # same number, different отделение
]


def _name(q):
    f = _pick_field(FIELDS, q)
    return f["name"] if f else None


def test_field_number_extraction():
    assert _field_number("Поле 47 · Тишанка") == "47"
    assert _field_number("Поле 76/108") == "76/108"
    assert _field_number("Поле 119") == "119"


def test_numeric_query_does_not_match_longer_number():
    # the actual reported bug: 47 must NOT resolve to «Поле 147»
    assert _name("47") in ("Поле 47 · Тишанка", "Поле 47 · Хлевище")
    assert "147" not in _name("47")
    assert _name("147") == "Поле 147 · Красное"


def test_pole_prefix_is_normalised():
    assert _name("поле 47") == _name("47")


def test_slash_and_plain_numbers():
    assert _name("76/108") == "Поле 76/108"
    assert _name("119") == "Поле 119"


def test_group_name_substring_still_works():
    # non-numeric queries keep the loose substring match (отделение names)
    assert _name("Тишанка") == "Поле 47 · Тишанка"


def test_unknown_returns_none():
    assert _name("999") is None
    assert _name("") is None

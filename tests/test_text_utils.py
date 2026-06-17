"""Small pure text helpers that parse LLM output / canonicalise labels. Cheap to
test, and they sit on the critical path (a bad JSON strip = a silent failure)."""
from bot.agro_chat import _clean_json
from bot.db import _norm_crop
from bot.weed_suggest import _parse


def test_clean_json_strips_markdown_fence():
    assert _clean_json('```json\n{"crop": "соя", "target": "осот"}\n```') == \
        {"crop": "соя", "target": "осот"}


def test_clean_json_finds_object_in_prose():
    assert _clean_json('Вот ответ: {"crop": null, "target": null} — всё.') == \
        {"crop": None, "target": None}


def test_clean_json_garbage_returns_none():
    assert _clean_json("не json вовсе") is None


def test_weed_parse_array():
    out = _parse('[{"ru":"Осот полевой","latin":"Sonchus arvensis"}]')
    assert out == [{"ru": "Осот полевой", "latin": "Sonchus arvensis"}]


def test_weed_parse_handles_fence_and_junk():
    assert _parse("```\n[]\n```") == []
    assert _parse("totally not json") == []


def test_norm_crop_pools_wheat_by_season():
    assert _norm_crop("Пшеница озимая") == "Озимая пшеница"
    assert _norm_crop("Озимая пшеница") == "Озимая пшеница"
    assert _norm_crop("Яровая пшеница") == "Яровая пшеница"
    # winter and spring must stay distinct (different phenology)
    assert _norm_crop("Пшеница озимая") != _norm_crop("Яровая пшеница")
    assert _norm_crop("Соя") == "Соя"

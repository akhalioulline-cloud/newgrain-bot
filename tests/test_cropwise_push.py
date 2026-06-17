"""Product / dose / work-type matching used when a logged operation is pushed to
CropWise. These are the brittle string-matching bits that decide whether a spray
lands on the right product and rate.
"""
from catalog.cropwise_push import (_match_product, _norm_prod, _split_dose,
                                    resolve_work_type)

# norm-name -> (applicable_type, id, base_unit_id), the shape load_catalogs builds
PRODS = {
    "корсар": ("Chemical", 10, 1),
    "семена яровой пшеницы гранова рс-1": ("Seed", 20, 2),
    "акцент": ("Chemical", 30, 1),
}


def test_norm_prod_strips_quotes_parens_and_tail():
    assert _norm_prod("«Корсар», ВРК (480 г/л)") == "корсар"
    assert _norm_prod("Акцент") == "акцент"


def test_exact_product_match():
    assert _match_product("Корсар", PRODS) == ("Chemical", 10, 1)


def test_unique_substring_match():
    # a short variety name still finds the full catalogue entry
    assert _match_product("Гранова", PRODS) == ("Seed", 20, 2)


def test_no_match_returns_none():
    assert _match_product("Раундап", PRODS) is None
    assert _match_product("", PRODS) is None


def test_split_dose():
    assert _split_dose("1.5 л/га") == (1.5, "л/га")
    assert _split_dose("0,15 ц/га") == (0.15, "ц/га")
    assert _split_dose("2 кг/га") == (2.0, "кг/га")
    assert _split_dose(None) == (None, None)
    assert _split_dose("по инструкции") == (None, None)


def test_resolve_work_type_by_keyword():
    # keyword in the operation text wins over the category default
    assert resolve_work_type({"operation": "опрыскивание гербицидом"}) == 1
    assert resolve_work_type({"operation": "посев сои"}) == 3
    assert resolve_work_type({"operation": "боронование"}) == 13


def test_resolve_work_type_falls_back_to_category():
    assert resolve_work_type({"operation": "что-то", "category": "harvest"}) == 7
    assert resolve_work_type({"operation": "", "category": "other"}) == 6

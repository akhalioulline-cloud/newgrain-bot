"""Report-paste resolvers + the «план агро работ» guard (Евгения's запрет).
Covers: report-line matching (work-type / machine / driver) and the plan lookup
that decides whether an operation is created-and-linked or blocked.
"""
from catalog.cropwise_report import (_area_of, driver_matches, find_plan, match_driver,
                                      match_machine, match_work_type, plan_summary)


# ---------- report-line resolvers ----------
def test_match_work_type_token_overlap():
    agri = [{"id": 1, "name": "Опрыскивание гербицидом"},
            {"id": 2, "name": "Боронование довсходовое"},
            {"id": 3, "name": "Культивация паровая"}]
    assert match_work_type("опрыскивание гербицидом", agri)["id"] == 1
    # too little overlap → no match (avoids confident-wrong work types)
    assert match_work_type("полив", agri) is None


def test_match_machine_by_number_anywhere():
    machines = [{"id": 5, "name": "Самоходный опрыскиватель", "registration_number": "Е 6448 АА"},
                {"id": 6, "name": "Амазон", "inventory_number": "5200"}]
    assert match_machine("6448", "самоходка", machines)["id"] == 5
    assert match_machine("5200", "амазон", machines)["id"] == 6
    assert match_machine("", "камаз", machines) is None


def test_match_driver_by_surname():
    users = [{"id": 7, "username": "Яровой Иван"}, {"id": 8, "username": "Черных"}]
    assert match_driver("Яровой", users)["id"] == 7
    assert match_driver("Черных", users)["id"] == 8
    assert match_driver("Неизвестный", users) is None


def test_match_driver_disambiguates_namesakes():
    users = [{"id": 1, "username": "Шапаренко Евгений Александрович"},
             {"id": 2, "username": "Шапаренко Сергей Петрович"}]
    # bare surname → first match (unchanged behaviour)
    assert match_driver("Шапаренко", users)["id"] == 1
    # given name picks the right namesake
    assert match_driver("Шапаренко Сергей", users)["id"] == 2
    assert match_driver("Шапаренко Евгений", users)["id"] == 1
    # an initial works too
    assert match_driver("Шапаренко С", users)["id"] == 2


def test_match_driver_disambiguates_by_patronymic():
    users = [{"id": 1, "username": "Купченко Николай Павлович"},
             {"id": 2, "username": "Купченко Николай Николаевич"}]
    # same surname AND first name → patronymic decides
    assert match_driver("Купченко Николай Николаевич", users)["id"] == 2
    assert match_driver("Купченко Николай Павлович", users)["id"] == 1


def test_match_driver_prefers_active_record():
    # CropWise has stale 'no_access' namesake duplicates — prefer the active one
    users = [{"id": 1, "username": "Тимошенко Владимир Николаевич", "status": "no_access"},
             {"id": 2, "username": "Тимошенко Владимир Николаевич", "status": "user"}]
    assert match_driver("Тимошенко Владимир Николаевич", users)["id"] == 2


def test_driver_matches_flags_true_ambiguity():
    # two ACTIVE people, identical full name → caller must ask (>1 candidate)
    users = [{"id": 1, "username": "Купченко Николай Николаевич", "status": "user"},
             {"id": 2, "username": "Купченко Николай Николаевич", "status": "user"}]
    assert len(driver_matches("Купченко Николай Николаевич", users)) == 2
    # but the given name resolving it uniquely → exactly one
    users2 = [{"id": 1, "username": "Шапаренко Евгений Александрович", "status": "user"},
              {"id": 2, "username": "Шапаренко Сергей Петрович", "status": "user"}]
    assert len(driver_matches("Шапаренко Сергей", users2)) == 1


def test_area_of():
    assert _area_of("167/104") == 104
    assert _area_of("121") is None


# ---------- the план агро работ guard ----------
def _idx():
    """Hand-built plan index mirroring load_plan_index()'s shape:
    field 100 is in отделение(group) 1 → папка(folder) 9; field 200 in group 2, no folder.
    Plan A: work_type 1 planned at the отделение level for group 1.
    Plan B: work_type 2 planned at the папка level for folder 9.
    """
    return {
        "field_group_of": {100: 1, 200: 2},
        "folder_of": {1: 9, 2: None},
        "plan_for": {
            (1, "FieldGroup", 1): 5001,
            (2, "GroupFolder", 9): 5002,
        },
    }


def test_find_plan_matches_at_otdelenie_level():
    assert find_plan(_idx(), 1, 100) == 5001


def test_find_plan_matches_at_folder_level():
    # field 100's group(1) rolls up to folder 9 → folder-level plan applies
    assert find_plan(_idx(), 2, 100) == 5002


def test_find_plan_blocks_unplanned_work_type():
    # work_type 3 is in no plan for this field → None → the op must be blocked
    assert find_plan(_idx(), 3, 100) is None


def test_find_plan_handles_missing_field_or_worktype():
    assert find_plan(_idx(), None, 100) is None
    assert find_plan(_idx(), 1, None) is None
    assert find_plan(_idx(), 1, 999) is None       # unknown field


def _plan(fields):
    return {"operation": "Опрыскивание", "work_type": {"id": 1, "name": "Опрыскивание гербицидом"},
            "machine": {"id": 5, "name": "Опрыскиватель"}, "machine_raw": "самоходка 6448",
            "driver": {"id": 7, "name": "Яровой"}, "driver_raw": "Яровой",
            "products": [{"name": "Корсар", "dose": "1.5 л/га", "matched": True}],
            "fields": fields}


def test_plan_summary_flags_unplanned_field():
    fields = [
        {"ref": "100/50", "field_id": 100, "shape": 1, "area": 50, "plan_id": 5001, "planned": True},
        {"ref": "200/30", "field_id": 200, "shape": 2, "area": 30, "plan_id": None, "planned": False},
    ]
    text = plan_summary(_plan(fields))
    assert "🚫" in text                    # the blocked field is flagged
    assert "не в «плане агро работ»" in text
    assert "Создать 1 агрооперац" in text  # only the planned field is counted

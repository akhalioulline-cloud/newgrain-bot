# «Задания машин» — how agronomists' field reports become CropWise tasks

*As of 2026-06-17. Source: real reports the agronomists send via Max to Евгения
(also our CropWise operator), who parses them by hand into CropWise. The `#NNNNN`
at the end of each is the resulting CropWise task number.*

This documents the report format + its CropWise mapping, as groundwork for
(eventually) automating Евгения's manual entry — an extension of the bot→CropWise
push (`docs/cropwise-push-status.md`), which today handles only single-field `/log`
ops without machine/driver.

## Report format (one report = one machine task = one `#` in CropWise)
```
<operation>                     ← line 1
<driver + machine + number>     ← line 2 (ORDER VARIES)
<product> - <dose>              ← 0+ tank-mix lines
<product> - <dose>
[Поля:]
<номер/площадь>                 ← 1+ fields, one per line
...
#NNNNN                          ← the completed CropWise task number
```

### Line 1 — operation
- Spray: «Обработка сои №1», «2-обработка сои», «Краевая обработка сои» (edge),
  «Обработка подсолнечника». Embeds **crop** (сои/подсолнечника) and **pass #** (№1, 2-).
- Logistics: «Подвоз воды [и гербицидов]», «Закачка воды» — machine tasks with **no
  products** (water haulage / loading).

### Line 2 — driver + machine + number (the new bit our bot doesn't capture)
Three sub-fields in **inconsistent order/separators**:
- `Яровой самоходка 6448`        → driver, machine-type, number
- `Черных 5628-Рсм 3000`         → driver, number, machine-model
- `6439-Шапаренко-Amazon 5.200`  → number, driver, machine-model
- `Гаврилов КамАЗ 928`           → driver, machine-type, number

Parsing rule that fits all: **driver = the Cyrillic surname**; **number = the 3–4-digit
machine inventory № (6448, 5628, 928…)**; **machine = the rest** (самоходка / РСМ 3000 /
Amazon 5200 / КамАЗ / ГАЗ — self-propelled & towed sprayers, or water trucks). Note a
second number can appear as part of the *model* (РСМ **3000**, Amazon **5.200**) — distinct
from the inventory №.

### Product lines — the tank mix
`<product> [-| ] <dose>` per line; multiple lines = one tank mix:
Миура 0.9 л/га · Когорта 2 л/га · Алсион 0.008 кг/га · Трейсер 0.3 л/га · Адью 0.2 л
(adjuvant) · Корсар 2.5 л/га · Имквант супер 1 л. Units: л/га, кг/га, sometimes bare л/кг.

### Fields
After optional «Поля:», one per line as `номер/площадь`: `167/104`, `40а/20` (note letter
suffixes). These match our `fields.name` style («Поле 121/140»).

## CropWise mapping (what Евгения enters)
| Report element | CropWise |
|---|---|
| operation + crop + pass | agro-operation **work_type** (Опрыскивание = protection) + crop + season |
| driver | the operator — likely the **machine's `default_driver_id`** (`/machines` has it) or a per-task responsible person |
| machine + number | a record in **`/machines`** (169 exist), matched by its inventory № |
| each product + dose | one **application_mix_item** (fact_rate/fact_amount), all on the op |
| field list | the task's fields/crop zones — **one task spans several fields** |
| `#NNNNN` | the resulting CropWise **task number** — almost certainly an **`/agri_work_plans`** id/number (the «задание»; `agro_operations.agri_work_plan_id` links to it), NOT `agro_operation.operation_number` (no match found) |

## VERIFIED against task #28225 (via API, 2026-06-17)
The web URL `operations.cropwise.com/machines/39/tasks/28225/edit` = API
`/machine_tasks/28225`. So the `#` is a **machine_task** id, filed under a machine —
a *different* resource than `agro_operations` (that's why the operation_number search
found nothing; it was never an access problem). All of it reads fine with our token:

- **`/machine_tasks/28225`** — machine_id 39, driver_id 169219, implement_id 110,
  **work_type_id 190 = «Краевая обработка сои гербицидами»** (the agronomic op type from
  line 1, crop-specific!), status done, season 2026, plus heavy **GPS telematics**
  (total/work distance, covered_area 75 ha, fuel, speeds, work timetable) — auto-captured
  from the machine's tracker. `related_agri_task_ids` / `related_transportation_task_ids`
  were **empty** on this task.
- **`/machines/39`** = «JD 4730 (6448ЕХ31) Самоходка», `machine_subtype: sprayer`,
  `registration_number: "6448ЕХ31"`. → report's «самоходка 6448» = this machine
  (the report № = the machine's registration number; `default_driver_id` is null, so the
  driver is set **per task**).
- **`/users/169219`** = «Яровой Владимир Николаевич». → report's «Яровой» = this driver.

**So a report maps to TWO parallel CropWise records:**
1. the **machine_task** (the `#`): machine + driver + implement + work_type + GPS — largely
   telematics-driven; carries the operation type (work_type 190).
2. the **agro_operation** (what we already sync): the fields + tank-mix products + doses.
On #28225 these weren't cross-linked (`related_agri_task_ids: []`) — they appear to coexist
as separate records of the same real work, which Евгения keys in from the one Max report.

**Access verdict: there is NO отделение access problem here.** The token read the machine,
its task, the driver, and the work-type without issue — the earlier "can't find #28225" was
purely me querying the wrong resource (`agro_operations` instead of `machine_tasks`).

## Open questions (confirm before automating)
1. **One task = one `agri_work_plan` spanning the fields, or N per-field `agro_operations`?**
   The single `#` per multi-field report points to one work-plan grouping. Need to see one
   entered record to be sure (the `#28225`-type tasks weren't visible to our API token —
   same отделение-coverage gap as the read sync; the report fields may be in отделения the
   token can't see).
2. **Driver link** — `machine.default_driver_id` vs a per-operation responsible person?
3. **Water-logistics tasks** (подвоз/закачка воды) — which work_type/category?
4. Machine inventory № → which `/machines` field (name / external_id / a number column)?

## To automate (future — bigger than today's `/log` push)
Parse this multi-line format (LLM), then: resolve machine № → `/machines`, driver → its
driver; build the tank mix; create the task (agri_work_plan + agro_operations across the
listed fields) with the machine assigned. Needs the field-coverage gap resolved (token must
see those отделения) and Q1–Q4 answered. The product/field/work_type mapping is already
solved (`catalog/cropwise_push.py`); the new work is the machine/driver + multi-field task.

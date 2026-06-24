---
name: newgrain-pyrus-prices
description: "Pyrus connector (alive) = АО НЗК's real historical product-price/payments source; bot must be added to payment lists to enumerate, then extract → product_prices"
metadata: 
  node_type: memory
  type: project
  originSessionId: 084cd08c-21cd-4a2f-a7a6-b222aac1fa68
---

**Pyrus = the farm's real historical price/payments source** for the Pilot-v2 savings loop (replaces the manual `/setprice` with real, multi-year prices). [[newgrain-pilot-v2]]

**Connector (ALIVE, verified 24 Jun):** MCP server at `/Users/akhaliullin/pyrus-mcp` (Python, `src/pyrus_mcp/` + README; FastMCP; auth = bot login + security key). Connected to org **«АО НЗК» (id 159058)** via bot account **"Claude" (person_id 1298833, `bot@…432c2444719c`, rights 8191)**. Tools: `mcp__pyrus__*` — whoami, list_forms, get_form, get_form_registry, list_catalogs, get_catalog, list_lists, get_list_tasks, get_inbox, **get_task**, **download_file**, create/comment_task (write — don't use). whoami/forms/catalogs/get_task all work.

**Data shape — payments are recorded as SIMPLE FREE-TEXT TASKS** (NOT via forms). Each task: supplier (Контрагент), invoice №+date, total ₽, often unit×qty in prose, **+ the invoice PDF attached** (downloadable via `download_file` / attachment URL). Verified on task **362300872** (email-subscription payment: ВК Цифровые Технологии, счёт 22.06.2026, 27 550 ₽, 79₽×29, invoice PDF attached). The forms «Согласование платежа» (1061600) + «Бюджет» (1061599) exist but their registries return EMPTY (unused / not the data path). Catalogs: Контрагенты (141262), Статья расходов (141263 — COARSE: «Сырьё и Материалы» = all СЗР/семена/удобрения/ГСМ mixed), Структура (135095).

**THE BLOCKER — enumeration, not access.** The bot reads any task BY ID (subscriber access works), but cannot LIST the historical payments: `get_inbox` empty (subscriber ≠ participant), and the yearly lists **«2021»/«2022»/«2023»/«2024»** + **«Оплата реестров»** are `list_type:private` and the bot is NOT in their member/manager ids → `get_list_tasks` returns empty. Org rights 8191 do NOT grant private-list membership. **FIX (founder, in Pyrus): add the Claude bot (id 1298833) as a MEMBER of the payment lists (2021/2022/2023/2024 + «Оплата реестров»)** — or wherever the payment tasks live. Then enumeration works.

**PLAN once enumerable (to build):** (1) enumerate payment tasks via `get_list_tasks` per list; (2) keep only materials/agro-supplier payments (skip salaries/taxes/rent — sensitive; scope tightly); (3) extract prices two ways — parse the task text (supplier · total ₽ · unit · qty · date) AND `download_file` + OCR the attached invoices/товарные накладные for line-item product × qty × unit price; (4) land a real multi-year **product-price history** → feed `product_prices` (pilot-v2 savings baseline) + cross-check the CropWise spray records. NOT a ready-made structured price table — it's an invoice ledger; product-level prices need text-parse + invoice OCR.

Serves [[newgrain-pilot-v2]] · [[newgrain-status-2026-05]].

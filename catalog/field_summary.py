"""Field data-layer summary CLI — prints the same integrated card as the /field
bot command (shared bot.db.field_card_text): operations by category, plant-
protection rotation per season×crop, recent treatments with active substances,
weather coverage, NDVI trend, and the catalog's candidate-product count.

Run: docker compose -f docker-compose.prod.yml run --rm -T bot \
       python -m catalog.field_summary "Поле 76/108"
"""
import argparse
import asyncio
import sys

from bot.db import field_card_text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("field")
    args = ap.parse_args()
    print(asyncio.run(field_card_text(args.field)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

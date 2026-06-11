"""create weather_daily + vegetation_weekly (agent climate/vigor inputs)

Per-field daily weather (temps, precip, snow, wind, soil moisture, humidity,
solar) and weekly vegetation (NDVI) + weather, from the farm's CropWise/meteoblue
exports. Tagged by source; unique per (field, date/week, source) for idempotent
reloads.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE weather_daily (
            id              SERIAL PRIMARY KEY,
            field_id        INTEGER REFERENCES fields(id),
            date            DATE NOT NULL,
            t_avg           NUMERIC,
            t_min           NUMERIC,
            t_max           NUMERIC,
            precip_mm       NUMERIC,
            snow_mm         NUMERIC,
            wind_ms         NUMERIC,
            soil_moist_top  NUMERIC,   -- 0–70 mm
            soil_moist_mid  NUMERIC,   -- 70–280 mm
            soil_moist_deep NUMERIC,   -- 280–1000 mm
            rel_humidity    NUMERIC,
            solar_wm2       NUMERIC,
            soil_surface_t  NUMERIC,
            source          TEXT,
            UNIQUE (field_id, date, source)
        )
        """
    )
    op.execute("CREATE INDEX idx_weather_date ON weather_daily (field_id, date)")
    op.execute(
        """
        CREATE TABLE vegetation_weekly (
            id             SERIAL PRIMARY KEY,
            field_id       INTEGER REFERENCES fields(id),
            week_start     DATE NOT NULL,
            week_no        INTEGER,
            ndvi           NUMERIC,
            t_avg          NUMERIC,
            t_min          NUMERIC,
            t_max          NUMERIC,
            soil_surface_t NUMERIC,
            precip_mm      NUMERIC,
            snow_mm        NUMERIC,
            source         TEXT,
            UNIQUE (field_id, week_start, source)
        )
        """
    )
    op.execute("CREATE INDEX idx_veg_week ON vegetation_weekly (field_id, week_start)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vegetation_weekly")
    op.execute("DROP TABLE IF EXISTS weather_daily")

"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-21

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.execute(
        """
        CREATE TABLE farms (
            id SERIAL PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            region VARCHAR(100),
            centroid GEOGRAPHY(POINT, 4326),
            total_ha NUMERIC(10,2),
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            tg_user_id BIGINT UNIQUE NOT NULL,
            phone VARCHAR(20),
            full_name VARCHAR(200),
            role VARCHAR(20) DEFAULT 'agronomist',
            farm_id INT REFERENCES farms(id),
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMP DEFAULT NOW(),
            last_active_at TIMESTAMP
        )
        """
    )

    op.execute(
        """
        CREATE TABLE fields (
            id SERIAL PRIMARY KEY,
            farm_id INT REFERENCES farms(id) NOT NULL,
            name VARCHAR(100) NOT NULL,
            crop VARCHAR(50),
            area_ha NUMERIC(8,2),
            geometry GEOGRAPHY(POLYGON, 4326),
            is_pilot BOOLEAN DEFAULT false,
            sowing_date DATE,
            season INT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_fields_pilot ON fields(is_pilot) WHERE is_pilot = true"
    )

    op.execute(
        """
        CREATE TABLE submissions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id INT REFERENCES users(id),
            field_id INT REFERENCES fields(id),
            category VARCHAR(30),
            subcategory VARCHAR(100),
            comment_text TEXT,
            comment_voice_url TEXT,
            comment_voice_text TEXT,
            captured_at TIMESTAMP,
            gps_lat NUMERIC(10,7),
            gps_lon NUMERIC(10,7),
            gps_source VARCHAR(20),
            image_url TEXT NOT NULL,
            image_width INT,
            image_height INT,
            image_phash VARCHAR(64),
            device_model VARCHAR(100),
            status VARCHAR(30) DEFAULT 'draft',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_subm_status ON submissions(status)")
    op.execute("CREATE INDEX idx_subm_field_date ON submissions(field_id, captured_at)")
    op.execute("CREATE INDEX idx_subm_phash ON submissions(image_phash)")

    op.execute(
        """
        CREATE TABLE weed_species (
            id SERIAL PRIMARY KEY,
            latin_name VARCHAR(100) NOT NULL,
            russian_name VARCHAR(100) NOT NULL,
            common_aliases TEXT[],
            is_regional_top BOOLEAN DEFAULT false,
            notes TEXT
        )
        """
    )

    op.execute(
        """
        CREATE TABLE treatments (
            id SERIAL PRIMARY KEY,
            field_id INT REFERENCES fields(id),
            treatment_date DATE NOT NULL,
            treatment_type VARCHAR(50),
            product_name VARCHAR(200),
            active_ingredient VARCHAR(200),
            dose_value NUMERIC(8,3),
            dose_unit VARCHAR(20),
            application_method VARCHAR(50),
            weather_temp_c NUMERIC(4,1),
            weather_wind_ms NUMERIC(4,1),
            weather_humidity NUMERIC(4,1),
            rain_24h_before_mm NUMERIC(5,1),
            rain_24h_after_mm NUMERIC(5,1),
            result_quality VARCHAR(20),
            result_notes TEXT,
            source VARCHAR(20),
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS treatments")
    op.execute("DROP TABLE IF EXISTS weed_species")
    op.execute("DROP TABLE IF EXISTS submissions")
    op.execute("DROP TABLE IF EXISTS fields")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS farms")

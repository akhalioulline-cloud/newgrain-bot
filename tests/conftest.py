"""Test bootstrap. These are PURE-LOGIC tests — they never open a socket — but
importing bot modules constructs a pydantic Settings and a SQLAlchemy engine at
import time, so we hand them a parseable dummy DB URL before anything is imported.
The engine is created but never connected, so no Postgres is required (CI-safe).
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("ADMIN_TG_IDS", "1")
# don't let a developer's real .env leak real endpoints into a test run
os.environ.setdefault("CROPWISE_OPERATIONS_TOKEN", "")

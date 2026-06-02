import aiosqlite
import os
from pathlib import Path

DATABASE_PATH = Path(__file__).parent / "votox.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def init_db():
    if not DATABASE_PATH.exists():
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = f.read()
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.executescript(schema)
            await db.commit()
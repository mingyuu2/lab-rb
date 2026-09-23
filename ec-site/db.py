import sqlite3
from pathlib import Path

from flask import g

DB_PATH = Path(__file__).parent / "ec_site.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        with conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            # Serialize the migration when multiple workers start together.
            # Existing reviews remain unrated; do not invent historical scores.
            conn.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
            if "rating" not in columns:
                conn.execute(
                    "ALTER TABLE reviews ADD COLUMN rating INTEGER "
                    "CHECK (rating BETWEEN 1 AND 5)"
                )
    finally:
        conn.close()

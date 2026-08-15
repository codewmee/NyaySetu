"""
Run this once:

    python fix_and_inspect_db.py

What it does:
  1. Adds any columns your models define but the live Neon tables are
     missing (currently: users.google_id, and relaxes users.password_hash
     to nullable) — safe, additive, won't touch existing data.
  2. Creates any tables that don't exist yet at all (case_documents, etc.)
     via create_all() — same as before, still safe.
  3. Prints EVERY table currently in your Neon database with its row count,
     so you can see at a glance which ones are stale/duplicate/unused
     before deleting anything. It does NOT delete anything automatically —
     deleting is destructive and you should eyeball this list first.
"""
import os
from dotenv import load_dotenv
from sqlalchemy import inspect, text

load_dotenv()

database_url = os.environ.get("DATABASE_URL")
print("DATABASE_URL in use:", database_url)

from flask import Flask
from db import db, init_db, User, Case, CaseDocument, ChatMessage  # noqa: F401

app = Flask(__name__)
init_db(app)  # runs create_all() for any wholly-missing tables

with app.app_context():
    inspector = inspect(db.engine)

    # ---- 1. patch columns that create_all() can't add to existing tables ----
    users_cols = {c["name"] for c in inspector.get_columns("users")}
    with db.engine.begin() as conn:
        if "google_id" not in users_cols:
            print("Adding users.google_id ...")
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN google_id VARCHAR(255) UNIQUE"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id)"
            ))
        else:
            print("users.google_id already present.")

        # relax NOT NULL on password_hash so Google-only signups don't 500
        col_info = next(c for c in inspector.get_columns("users") if c["name"] == "password_hash")
        if not col_info["nullable"]:
            print("Relaxing users.password_hash to nullable ...")
            conn.execute(text(
                "ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL"
            ))
        else:
            print("users.password_hash already nullable.")

    # ---- 2. re-run create_all() in case any whole tables were missing ----
    db.create_all()

    # ---- 3. full inventory: every table + row count ----
    inspector = inspect(db.engine)  # refresh after any DDL above
    tables = sorted(inspector.get_table_names())
    print("\n--- Tables in this database ---")
    with db.engine.connect() as conn:
        for t in tables:
            try:
                count = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
            except Exception as e:
                count = f"error: {e}"
            print(f"  {t:<25} {count} row(s)")

    known_models = {"users", "cases", "case_documents", "chat_messages"}
    unknown = [t for t in tables if t not in known_models and not t.startswith("alembic")]
    if unknown:
        print("\n--- Tables NOT defined in db.py (candidates for cleanup) ---")
        for t in unknown:
            print(f"  {t}")
        print(
            "\nThese aren't referenced by any current model. If you recognize them as "
            "leftovers from an older version of the app, you can drop them manually, e.g.:\n"
            '    DROP TABLE "table_name";\n'
            "Review each one before dropping — this script won't do it for you."
        )
    else:
        print("\nNo unexpected tables found — schema matches your models.")

print("\nDone. Restart your Flask app now.")
"""
Standalone migration: creates the articles + feed_sources tables and adds
an is_admin flag to the existing users table.

    python migrate_articles.py

This assumes your User model's table is named "users" (SQLAlchemy's default
for a class named User) — if you've set a custom __tablename__, change the
string below to match.
"""
import os
from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import inspect, text

from db import db, init_db
import articles_models  # noqa: F401 — registers Article/FeedSource on db.metadata

load_dotenv()

USERS_TABLE = "users"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "migration-temp-key")
init_db(app)

with app.app_context():
    db.create_all()
    print("Ensured articles + feed_sources tables exist.")

    inspector = inspect(db.engine)
    existing_columns = [c["name"] for c in inspector.get_columns(USERS_TABLE)]

    if "is_admin" not in existing_columns:
        db.session.execute(text(f"ALTER TABLE {USERS_TABLE} ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE"))
        db.session.commit()
        print("Added is_admin column to", USERS_TABLE)
    else:
        print("is_admin column already exists.")

print("Migration complete.")
print()
print("Make yourself an admin (run in a Python shell):")
print("  from app import app")
print("  from db import db, User")
print("  with app.app_context():")
print("      u = User.query.filter_by(email='you@example.com').first()")
print("      u.is_admin = True")
print("      db.session.commit()")
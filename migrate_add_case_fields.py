"""
Run once: python migrate_add_case_fields.py
Adds the new wizard-detail columns to the existing cases table.
"""
import os
from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()

from flask import Flask
from db import db, init_db

app = Flask(__name__)
init_db(app)

STATEMENTS = [
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS incident_date DATE",
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS ongoing BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS city VARCHAR(100)",
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS state VARCHAR(100)",
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS other_party VARCHAR(255)",
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS amount DOUBLE PRECISION",
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS additional_notes TEXT",
]

with app.app_context():
    for stmt in STATEMENTS:
        print("Running:", stmt)
        db.session.execute(text(stmt))
    db.session.commit()
    print("Done.")
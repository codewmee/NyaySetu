"""
Run this once to diagnose/fix the missing case_documents table:

    python check_db.py

It prints which DATABASE_URL is actually being used and which tables
currently exist, then creates any that are missing (case_documents included).
"""
import os
from dotenv import load_dotenv
from sqlalchemy import inspect

load_dotenv()

database_url = os.environ.get("DATABASE_URL")
print("DATABASE_URL in use:", database_url)

from flask import Flask
from db import db, init_db, User, Case, CaseDocument  # noqa: F401 (models must be imported)

app = Flask(__name__)
init_db(app)  # this itself calls db.create_all()

with app.app_context():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print("Tables that exist right now:", tables)

    if "case_documents" not in tables:
        print("case_documents still missing — forcing create_all() again...")
        db.create_all()
        tables = inspect(db.engine).get_table_names()
        print("Tables after create_all():", tables)
    else:
        print("case_documents exists. You're good — just restart your app server.")
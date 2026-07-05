"""
Article + feed source models for the Know Your Rights CMS.
Imports the shared `db` instance from db.py so these tables live in the
same Postgres database as everything else.
"""

import json
from datetime import datetime

from db import db

CATEGORY_META = {
    "property": {"label": "Property", "icon": "tenents_right.png"},
    "employment": {"label": "Employment", "icon": "employ_right.png"},
    "consumer": {"label": "Consumer", "icon": "consumer_right.png"},
    "rti": {"label": "RTI", "icon": "docs.png"},
    "women": {"label": "Women's Rights", "icon": "women_rights.png"},
    "family": {"label": "Family", "icon": "family_right.png"},
    "cyber": {"label": "Cyber Crime", "icon": "cyber_rights.png"},
    "criminal": {"label": "Criminal Justice", "icon": "criminal_rights.png"},
    "other": {"label": "General", "icon": "docs.png"},
}


class FeedSource(db.Model):
    __tablename__ = "feed_sources"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    url = db.Column(db.String(500), nullable=False, unique=True)
    default_category = db.Column(db.String(50), nullable=False, default="other")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    fetch_interval_minutes = db.Column(db.Integer, nullable=False, default=60)
    last_fetched_at = db.Column(db.DateTime, nullable=True)
    last_fetch_status = db.Column(db.String(20), nullable=True)  # "ok" | "error"
    last_fetch_message = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    @property
    def is_due(self):
        if not self.is_active:
            return False
        if self.last_fetched_at is None:
            return True
        elapsed_minutes = (
            datetime.utcnow() - self.last_fetched_at
        ).total_seconds() / 60
        return elapsed_minutes >= self.fetch_interval_minutes


class Article(db.Model):
    __tablename__ = "articles"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(220), nullable=False, unique=True, index=True)
    title = db.Column(db.String(300), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    body_html = db.Column(db.Text, nullable=False)

    category = db.Column(db.String(50), nullable=False, default="other", index=True)
    image_url = db.Column(db.String(500), nullable=True)
    read_time_minutes = db.Column(db.Integer, nullable=True)
    status = db.Column(
        db.String(20), nullable=False, default="published"
    )  # draft | published

    # Optional extra structure for manually-written pieces — RSS-sourced
    # articles usually leave these blank and just use body_html.
    scenario = db.Column(db.Text, nullable=True)
    checklist_json = db.Column(db.Text, nullable=True)  # JSON list[str]
    relevant_law_json = db.Column(db.Text, nullable=True)  # JSON list[str]

    source_type = db.Column(
        db.String(20), nullable=False, default="manual"
    )  # manual | rss
    source_name = db.Column(db.String(150), nullable=True)
    source_url = db.Column(db.String(500), nullable=True, unique=True)
    feed_id = db.Column(db.Integer, db.ForeignKey("feed_sources.id"), nullable=True)

    published_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    feed = db.relationship("FeedSource", backref="articles")

    @property
    def category_label(self):
        return CATEGORY_META.get(self.category, CATEGORY_META["other"])["label"]

    @property
    def category_icon(self):
        return CATEGORY_META.get(self.category, CATEGORY_META["other"])["icon"]

    @property
    def checklist(self):
        return json.loads(self.checklist_json) if self.checklist_json else []

    @property
    def relevant_law(self):
        return json.loads(self.relevant_law_json) if self.relevant_law_json else []

import os
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def init_db(app):
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL env var not set (your Neon connection string)")

    # Neon sometimes gives postgres:// — SQLAlchemy wants postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    with app.app_context():
        db.create_all()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cases = db.relationship(
        "Case", backref="user", lazy=True, cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def first_name(self):
        """Short display name used in greetings / the avatar chip."""
        if self.name:
            return self.name.strip().split(" ")[0]
        return self.email.split("@")[0]

    @property
    def initial(self):
        source = self.name or self.email
        return source.strip()[0].upper() if source.strip() else "U"


class Case(db.Model):
    """A user's legal issue/case, shown in the 'My Cases' dashboard section."""

    __tablename__ = "cases"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(100), nullable=True)

    status = db.Column(db.String(30), nullable=False, default="in_progress")
    # status one of: in_progress, awaiting_action, resolved, closed

    strength = db.Column(db.Integer, nullable=False, default=0)  # 0-100

    icon = db.Column(db.String(10), nullable=False, default="📁")
    icon_bg = db.Column(db.String(20), nullable=False, default="#eef0ff")
    icon_color = db.Column(db.String(20), nullable=False, default="#5b4dee")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    STATUS_LABELS = {
        "in_progress": "In Progress",
        "awaiting_action": "Awaiting Action",
        "resolved": "Resolved",
        "closed": "Closed",
    }

    STRENGTH_COLORS = {
        "low": "#d97706",     # < 40
        "medium": "#7c3aed",  # 40-69
        "high": "#16a34a",    # 70+
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status.replace("_", " ").title())

    @property
    def strength_color(self):
        if self.strength >= 70:
            return self.STRENGTH_COLORS["high"]
        if self.strength >= 40:
            return self.STRENGTH_COLORS["medium"]
        return self.STRENGTH_COLORS["low"]

    @property
    def date(self):
        return self.created_at.strftime("%d %b %Y") if self.created_at else ""
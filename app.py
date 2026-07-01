import os
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, render_template, session, redirect, url_for, request, flash

from db import db, init_db, User, Case

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-this-later")

init_db(app)


def current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return db.session.get(User, user_id)


def greeting_key_for_now():
    hour = datetime.now().hour
    if hour < 12:
        return "greetingMorning"
    if hour < 17:
        return "greetingAfternoon"
    return "greetingEvening"


RECENT_ACTIVITY = [
    {
        "icon": "🗂️",
        "icon_bg": "#dbeafe",
        "icon_color": "#2563eb",
        "text": "Case updated: Unpaid Salary Dispute",
        "time": "2 hours ago",
    },
    {
        "icon": "📄",
        "icon_bg": "#dcfce7",
        "icon_color": "#16a34a",
        "text": "Document analyzed: rental_agreement.pdf",
        "time": "Yesterday",
    },
    {
        "icon": "📌",
        "icon_bg": "#fce7f3",
        "icon_color": "#db2777",
        "text": "New case created: Security Deposit Refund",
        "time": "2 days ago",
    },
]


@app.route("/")
def home():
    user = current_user()

    if not user:
        return render_template("index.html", active_page="home", user=None)

    cases = Case.query.filter_by(user_id=user.id).order_by(Case.created_at.desc()).all()

    return render_template(
        "index.html",
        active_page="dashboard",
        user=user,
        greeting_key=greeting_key_for_now(),
        cases=cases,
        activity=RECENT_ACTIVITY,
    )


# ---------------- Local login/signup ----------------
@app.route("/login")
def login_page():
    if current_user():
        return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/signup", methods=["POST"])
def signup():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    name = request.form.get("name", "").strip()

    if not email or not password:
        flash("Email and password are required.")
        return redirect(url_for("login_page"))

    if len(password) < 6:
        flash("Password must be at least 6 characters long.")
        return redirect(url_for("login_page"))

    if User.query.filter_by(email=email).first():
        flash("An account with this email already exists.")
        return redirect(url_for("login_page"))

    user = User(email=email, name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    session["user_id"] = user.id
    return redirect(url_for("home"))


@app.route("/login", methods=["POST"])
def login_submit():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash("Invalid email or password.")
        return redirect(url_for("login_page"))

    session["user_id"] = user.id
    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("home"))


# ---------------- placeholder routes ----------------
@app.route("/my-issues")
def my_issues():
    return "My Issues page (coming soon)"


@app.route("/document-helper")
def document_helper():
    return "Document Helper page (coming soon)"


@app.route("/know-your-rights")
def know_rights():
    return "Know Your Rights page (coming soon)"


@app.route("/saved-reports")
def saved_reports():
    return "Saved Reports page (coming soon)"


@app.route("/government-services")
def government_services():
    return "Government Services page (coming soon)"


@app.route("/help-support")
def help_support():
    return "Help & Support page (coming soon)"


@app.route("/settings")
def settings_page():
    return "Settings page (coming soon)"


@app.route("/find-lawyer")
def find_lawyer():
    return "Find a Lawyer page (coming soon)"


@app.route("/issues/<category>")
def issue_category(category):
    return f"Issue category page: {category} (coming soon)"


@app.route("/set-language/<lang>")
def set_language(lang):
    if lang in ("en", "hi", "mr"):
        session["current_language"] = lang
    return redirect(request.referrer or url_for("home"))


if __name__ == "__main__":
    app.run(debug=True, port=9000)

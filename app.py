import os
import json
import uuid
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, render_template, session, redirect, url_for, request, flash, jsonify
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader

from db import db, init_db, User, Case, CaseDocument, ChatMessage
from legal_ai import get_legal_ai_reply
from articles_models import Article, FeedSource, CATEGORY_META
from rss_ingest import fetch_all_active_feeds
from admin_routes import admin_bp

load_dotenv()

app = Flask(__name__)

# ---------------- Secret key (REQUIRED from .env, no hardcoded fallback) ----------------
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY env var not set. Add a long random string to your .env, e.g.\n"
        "SECRET_KEY=" + uuid.uuid4().hex + uuid.uuid4().hex
    )
app.secret_key = SECRET_KEY

# ---------------- Neon Postgres (users + cases) ----------------
init_db(app)

# ---------------- Cloudinary (file storage: PDFs, images, etc.) ----------------

CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")

if not CLOUDINARY_CLOUD_NAME or not CLOUDINARY_API_KEY or not CLOUDINARY_API_SECRET:
    raise RuntimeError(
        "CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET env vars not set "
        "(add them to your .env)"
    )

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True,
)


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

# Maps the value of each category radio button in the New Issue form to the
# display label + icon styling used both on the form and on the resulting
# Case card in the dashboard.
# Kept as its own name — this used to be called CATEGORY_META too, which
# silently overwrote the CATEGORY_META imported from articles_models above,
# breaking category display on /articles and /articles/<slug>.
CASE_CATEGORY_META = {
    "job": {"label": "Job & Employment", "icon": "💼", "icon_bg": "#e3e8ff", "icon_color": "#4a4ad9"},
    "landlord": {"label": "Landlord & Tenant", "icon": "🏠", "icon_bg": "#ffe9d6", "icon_color": "#d97706"},
    "consumer": {"label": "Consumer Complaint", "icon": "🛒", "icon_bg": "#ffe1e1", "icon_color": "#dc2626"},
    "cyber": {"label": "Cyber Crime", "icon": "🔒", "icon_bg": "#d8ecff", "icon_color": "#0d6ec7"},
    "loan": {"label": "Loan & Recovery", "icon": "💰", "icon_bg": "#dafbe8", "icon_color": "#16a34a"},
    "family": {"label": "Family & Personal", "icon": "👪", "icon_bg": "#ede4ff", "icon_color": "#7c3aed"},
    "property": {"label": "Property Dispute", "icon": "🏢", "icon_bg": "#ffe3ec", "icon_color": "#db2777"},
    "other": {"label": "Other", "icon": "•••", "icon_bg": "#f3f4f6", "icon_color": "#4b5563"},
}

@app.route("/know_rights")
def urrights():
    return render_template("know_your_rights.html")

@app.route("/articles")
def articles_page():
    articles = Article.query.filter_by(status="published").order_by(Article.published_at.desc()).all()
    return render_template(
        "admin/articles.html",
        active_page="articles",
        user=current_user(),
        articles=articles,
        category_meta=CATEGORY_META,
    )


@app.route("/articles/<slug>")
def article_detail(slug):
    article = Article.query.filter_by(slug=slug, status="published").first()
    if not article:
        return redirect(url_for("articles_page"))

    related = (
        Article.query.filter(
            Article.category == article.category,
            Article.id != article.id,
            Article.status == "published",
        )
        .order_by(Article.published_at.desc())
        .limit(2)
        .all()
    )

    return render_template(
        "article_detail.html",
        article=article,
        related=related,
        category_meta=CATEGORY_META,
        user=current_user(),
        active_page="articles",
    )


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


# ---------------- Full-screen case chat ----------------
# The landing page's small intake console only captures the user's first
# message (stashed into sessionStorage as 'nyaysetu_initial_message') and
# redirects here. This page owns the actual back-and-forth with Gemini via
# /api/legal-chat, including any file attachments.
#
# Pass ?case_id=<id> to resume an existing case's conversation (e.g. the
# "Continue conversation" button on a dashboard case card) — otherwise a
# fresh Case row is created on the first message sent from here.
@app.route("/chat")
def legal_chat_page():
    user = current_user()
    if not user:
        return redirect(url_for("login_page"))

    case = None
    case_id = request.args.get("case_id")
    if case_id:
        case = Case.query.filter_by(id=case_id, user_id=user.id).first()

    history = [m.to_history_dict() for m in case.messages] if case else []

    return render_template(
        "chat.html",
        active_page="chat",
        user=user,
        case=case,
        history=history,
    )


# ---------------- AI legal intake chat (Gemini) ----------------
@app.route("/api/legal-chat", methods=["POST"])
def legal_chat():
    """
    Accepts either:
      - JSON: { "message": str, "history": [...], "case_id": int|null }
      - multipart/form-data (when files are attached): same fields, plus
        one or more files under the "documents" field.

    On the first call for a conversation (no case_id, or an id that doesn't
    resolve to one of the user's cases) a new Case row is created — its
    title/description/category/strength get filled in and kept in sync from
    whatever Gemini infers on each turn. Every user + model turn is saved as
    a ChatMessage so the conversation can be reloaded later via
    GET /chat?case_id=<id>. Any attached files are uploaded to Cloudinary and
    saved as CaseDocument rows, same as the /new-issue flow.

    Returns: { "type": "question"|"answer"|"off_topic", "reply": str,
               "category": str|null, "summary": str|null, "strength": int|null,
               "case_id": int, "uploaded_count": int }
    """
    user = current_user()
    if not user:
        return jsonify({"error": "login required"}), 401

    is_multipart = (request.content_type or "").startswith("multipart/form-data")

    if is_multipart:
        message = (request.form.get("message") or "").strip()
        case_id = request.form.get("case_id") or None
        try:
            history = json.loads(request.form.get("history") or "[]")
        except ValueError:
            history = []
        files = request.files.getlist("documents")
    else:
        data = request.get_json(silent=True) or {}
        message = (data.get("message") or "").strip()
        case_id = data.get("case_id") or None
        history = data.get("history") or []
        files = []

    if not message and not files:
        return jsonify({"error": "message is required"}), 400

    # Keep the payload sane — only send the most recent turns to Gemini.
    if len(history) > 30:
        history = history[-30:]

    # ---- find or create the Case this conversation belongs to ----
    case = None
    if case_id:
        case = Case.query.filter_by(id=case_id, user_id=user.id).first()

    if not case:
        title = message if message else "New conversation"
        title = title if len(title) <= 60 else title[:60].rstrip() + "…"
        case = Case(
            user_id=user.id,
            title=title,
            description=message or None,
            status="in_progress",
            strength=20,
        )
        db.session.add(case)
        db.session.commit()  # need case.id below, for the Cloudinary folder + FK rows

    if message:
        db.session.add(ChatMessage(case_id=case.id, role="user", content=message))

    # ---- upload any attached files to Cloudinary (same pattern as /new-issue) ----
    uploaded_count = 0
    failed_count = 0
    for f in files:
        if not f or not f.filename:
            continue

        safe_name = secure_filename(f.filename) or "file"
        name_no_ext = os.path.splitext(safe_name)[0] or "file"
        public_id = f"{uuid.uuid4().hex}_{name_no_ext}"
        content_type = f.mimetype or "application/octet-stream"

        try:
            upload_result = cloudinary.uploader.upload(
                f,
                folder=f"nyaysetu/cases/{case.id}",
                public_id=public_id,
                resource_type="auto",
                use_filename=False,
                unique_filename=False,
                overwrite=False,
            )
        except Exception:
            app.logger.exception("Cloudinary upload failed for %s", f.filename)
            failed_count += 1
            continue

        db.session.add(CaseDocument(
            case_id=case.id,
            file_name=f.filename,
            cloudinary_public_id=upload_result.get("public_id"),
            cloudinary_url=upload_result.get("secure_url"),
            resource_type=upload_result.get("resource_type"),
            content_type=content_type,
            bytes=upload_result.get("bytes"),
        ))
        uploaded_count += 1

    db.session.commit()

    try:
        result = get_legal_ai_reply(history, message)
    except Exception:
        app.logger.exception("Gemini call failed")
        result = {
            "type": "answer",
            "reply": "Something went wrong reaching the AI — please try again in a moment.",
            "category": None,
            "summary": None,
            "strength": None,
        }

    db.session.add(ChatMessage(case_id=case.id, role="model", content=result.get("reply", "")))

    # Keep the Case row in sync with whatever Gemini has inferred so far.
    if result.get("category"):
        case.category = result["category"]
    if result.get("summary"):
        case.description = result["summary"]
        case.title = (
            result["summary"] if len(result["summary"]) <= 60
            else result["summary"][:60].rstrip() + "…"
        )
    if result.get("strength") is not None:
        case.strength = result["strength"]

    db.session.commit()

    result["case_id"] = case.id
    result["uploaded_count"] = uploaded_count
    result["failed_count"] = failed_count
    return jsonify(result)


# ---------------- New Issue wizard ----------------
@app.route("/new-issue", methods=["GET", "POST"])
def new_issue():
    user = current_user()
    if not user:
        return redirect(url_for("login_page"))

    if request.method == "POST":
        description = request.form.get("description", "").strip()
        category_key = request.form.get("category", "other")

        if not description:
            flash("Please describe your issue before submitting.")
            return redirect(url_for("new_issue"))

        meta = CASE_CATEGORY_META.get(category_key, CASE_CATEGORY_META["other"])

        # A short, human-readable title derived from the free-text description.
        title = description if len(description) <= 60 else description[:60].rstrip() + "…"

        case = Case(
            user_id=user.id,
            title=title,
            description=description,
            category=meta["label"],
            status="in_progress",
            strength=40,
            icon=meta["icon"],
            icon_bg=meta["icon_bg"],
            icon_color=meta["icon_color"],
        )
        db.session.add(case)
        db.session.commit()  # need case.id before we can attach documents to it

        # Upload each attached file to Cloudinary, then store only the
        # resulting public_id/URL in Neon — never the raw file bytes.
        documents = request.files.getlist("documents")
        uploaded_count = 0
        failed_count = 0

        for f in documents:
            if not f or not f.filename:
                continue

            safe_name = secure_filename(f.filename) or "file"
            name_no_ext = os.path.splitext(safe_name)[0] or "file"
            public_id = f"{uuid.uuid4().hex}_{name_no_ext}"
            content_type = f.mimetype or "application/octet-stream"

            try:
                upload_result = cloudinary.uploader.upload(
                    f,
                    folder=f"nyaysetu/cases/{case.id}",
                    public_id=public_id,
                    resource_type="auto",  # auto-detects image vs pdf/raw
                    use_filename=False,
                    unique_filename=False,
                    overwrite=False,
                )
            except Exception as exc:  # network/credentials/quota issues, etc.
                app.logger.exception("Cloudinary upload failed for %s", f.filename)
                failed_count += 1
                continue

            doc = CaseDocument(
                case_id=case.id,
                file_name=f.filename,
                cloudinary_public_id=upload_result.get("public_id"),
                cloudinary_url=upload_result.get("secure_url"),
                resource_type=upload_result.get("resource_type"),
                content_type=content_type,
                bytes=upload_result.get("bytes"),
            )
            db.session.add(doc)
            uploaded_count += 1

        if uploaded_count or failed_count:
            db.session.commit()

        if failed_count:
            flash(f"Issue submitted. {uploaded_count} document(s) uploaded, {failed_count} failed — please retry those.")
        elif uploaded_count:
            flash(f"Your issue was submitted with {uploaded_count} document(s) attached.")
        else:
            flash("Your issue has been submitted.")

        return redirect(url_for("home"))

    return render_template(
        "new_issue.html",
        active_page="newissue",
        user=user,
        greeting_key=greeting_key_for_now(),
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
@app.route("/api/cases/<int:case_id>/resolve", methods=["POST"])
def resolve_case(case_id):
    user = current_user()
    if not user:
        return jsonify({"error": "login required"}), 401

    case = Case.query.filter_by(id=case_id, user_id=user.id).first()
    if not case:
        return jsonify({"error": "not found"}), 404

    case.status = "resolved"
    db.session.commit()
    return jsonify({"ok": True, "status": case.status, "status_label": case.status_label})


@app.route("/dashboard")
def my_issues():
    user = current_user()
    if not user:
        return redirect(url_for("login_page"))

    cases = Case.query.filter_by(user_id=user.id).order_by(Case.created_at.desc()).all()

    return render_template(
        "dashboard.html",
        active_page="dashboard",
        user=user,
        cases=cases,
        activity=RECENT_ACTIVITY,
    )


@app.route("/document-helper")
def document_helper():
    return "Document Helper page (coming soon)"


@app.route("/know-your-rights")
def know_rights_redirect():
    # old placeholder path — kept alive as a redirect in case it's linked
    # anywhere else; the real destination is now /articles
    return redirect(url_for("articles_page"))


@app.route("/saved-reports")
def saved_reports():
    return "Saved Reports page (coming soon)"


@app.route("/government-services")
def government_services():
    return "Government Services page (coming soon)"


@app.route("/help-support")
def help_support():
    return render_template("help.html")


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
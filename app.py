import os
import uuid
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, session, redirect, url_for, request, flash
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader
import google.generativeai as genai

from db import db, init_db, User, Case, CaseDocument, ChatMessage

load_dotenv()

app = Flask(__name__)

# ---------------- Secret key ----------------
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY env var not set. Add a long random string to your .env, e.g.\n"
        "SECRET_KEY=" + uuid.uuid4().hex + uuid.uuid4().hex
    )
app.secret_key = SECRET_KEY

# ---------------- Neon Postgres ----------------
init_db(app)

# ---------------- Cloudinary ----------------
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")

if not CLOUDINARY_CLOUD_NAME or not CLOUDINARY_API_KEY or not CLOUDINARY_API_SECRET:
    raise RuntimeError(
        "CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET env vars not set"
    )

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True,
)

# ---------------- Gemini (case analysis chat) ----------------
# Expects in your .env:
#   GEMINI_API_KEY=AIza...
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY env var not set (add it to your .env)")

genai.configure(api_key=GEMINI_API_KEY)
CHAT_MODEL = "gemini-2.5-flash"

CASE_CHAT_SYSTEM_PROMPT = """You are NyaySetu's legal case assistant. A user in India has just submitted a \
legal issue. Here is everything already known about their case — never ask about anything already covered here:

{case_context}

Your job in this chat:
1. On your very first message, give a short plain-language analysis (3-5 sentences): what this issue likely \
involves legally, what the case strength score suggests, and what kind of remedy is typically available. \
No legal jargon. Briefly note, once, that this isn't formal legal advice.
2. After that, only ask a follow-up question if there is a genuine, specific gap that would meaningfully \
change your guidance (missing dates, missing amounts, ambiguous facts, unclear evidence). Ask exactly ONE \
question per message.
3. NEVER repeat a question already answered — either in the case details above or earlier in this chat.
4. If you already have enough to give solid guidance, say so plainly and give 2-3 concrete next steps \
instead of asking anything.
5. Keep every reply under 120 words."""


def build_case_context(case):
    parts = [
        f"Title: {case.title}",
        f"Description: {case.description or 'N/A'}",
        f"Category: {case.category or 'N/A'}",
    ]
    if case.incident_date:
        parts.append(f"Incident date: {case.incident_date}")
    if case.ongoing:
        parts.append("This is an ongoing issue.")
    location = " ".join(filter(None, [case.city, case.state]))
    if location:
        parts.append(f"Location: {location}")
    if case.other_party:
        parts.append(f"Other party: {case.other_party}")
    if case.amount:
        parts.append(f"Amount involved: ₹{case.amount:.0f}")
    if case.additional_notes:
        parts.append(f"Additional notes: {case.additional_notes}")
    parts.append(f"Case strength score: {case.strength}/100")
    parts.append(f"Documents attached: {len(case.documents)}")
    return "\n".join(parts)


def get_chat_model(case):
    system_prompt = CASE_CHAT_SYSTEM_PROMPT.format(case_context=build_case_context(case))
    return genai.GenerativeModel(CHAT_MODEL, system_instruction=system_prompt)


def generate_opening_message(case):
    model = get_chat_model(case)
    chat = model.start_chat(history=[])
    response = chat.send_message("Give your initial analysis of this case now, following your instructions.")
    return response.text


def generate_reply(case, all_messages):
    """all_messages must include the latest user message as the last item."""
    model = get_chat_model(case)
    history = [{"role": m.role, "parts": [m.content]} for m in all_messages[:-1]]
    chat = model.start_chat(history=history)
    response = chat.send_message(all_messages[-1].content)
    return response.text


def upload_documents_for_case(case, files):
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

    return uploaded_count, failed_count


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
    {"icon": "🗂️", "icon_bg": "#dbeafe", "icon_color": "#2563eb", "text": "Case updated: Unpaid Salary Dispute", "time": "2 hours ago"},
    {"icon": "📄", "icon_bg": "#dcfce7", "icon_color": "#16a34a", "text": "Document analyzed: rental_agreement.pdf", "time": "Yesterday"},
    {"icon": "📌", "icon_bg": "#fce7f3", "icon_color": "#db2777", "text": "New case created: Security Deposit Refund", "time": "2 days ago"},
]

CATEGORY_META = {
    "job": {"label": "Job & Employment", "icon": "💼", "icon_bg": "#e3e8ff", "icon_color": "#4a4ad9"},
    "landlord": {"label": "Landlord & Tenant", "icon": "🏠", "icon_bg": "#ffe9d6", "icon_color": "#d97706"},
    "consumer": {"label": "Consumer Complaint", "icon": "🛒", "icon_bg": "#ffe1e1", "icon_color": "#dc2626"},
    "cyber": {"label": "Cyber Crime", "icon": "🔒", "icon_bg": "#d8ecff", "icon_color": "#0d6ec7"},
    "loan": {"label": "Loan & Recovery", "icon": "💰", "icon_bg": "#dafbe8", "icon_color": "#16a34a"},
    "family": {"label": "Family & Personal", "icon": "👪", "icon_bg": "#ede4ff", "icon_color": "#7c3aed"},
    "property": {"label": "Property Dispute", "icon": "🏢", "icon_bg": "#ffe3ec", "icon_color": "#db2777"},
    "other": {"label": "Other", "icon": "•••", "icon_bg": "#f3f4f6", "icon_color": "#4b5563"},
}


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

        meta = CATEGORY_META.get(category_key, CATEGORY_META["other"])
        title = description if len(description) <= 60 else description[:60].rstrip() + "…"

        incident_date_raw = request.form.get("incident_date", "").strip()
        incident_date = None
        if incident_date_raw:
            try:
                incident_date = datetime.strptime(incident_date_raw, "%Y-%m-%d").date()
            except ValueError:
                incident_date = None

        amount_raw = request.form.get("amount", "").strip()
        try:
            amount = float(amount_raw) if amount_raw else None
        except ValueError:
            amount = None

        case = Case(
            user_id=user.id,
            title=title,
            description=description,
            category=meta["label"],
            incident_date=incident_date,
            ongoing=request.form.get("ongoing") == "on",
            city=request.form.get("city", "").strip() or None,
            state=request.form.get("state", "").strip() or None,
            other_party=request.form.get("other_party", "").strip() or None,
            amount=amount,
            additional_notes=request.form.get("additional_notes", "").strip() or None,
            status="in_progress",
            strength=40,
            icon=meta["icon"],
            icon_bg=meta["icon_bg"],
            icon_color=meta["icon_color"],
        )
        db.session.add(case)
        db.session.commit()

        documents = request.files.getlist("documents")
        uploaded_count, failed_count = upload_documents_for_case(case, documents)

        if failed_count:
            flash(f"Issue submitted. {uploaded_count} document(s) uploaded, {failed_count} failed — please retry those.")
        elif uploaded_count:
            flash(f"Your issue was submitted with {uploaded_count} document(s) attached.")
        else:
            flash("Your issue has been submitted.")

        # AI analysis chat kicks off right after case creation
        return redirect(url_for("case_chat", case_id=case.id))

    return render_template(
        "new_issue.html",
        active_page="newissue",
        user=user,
        greeting_key=greeting_key_for_now(),
    )


# ---------------- AI case analysis chat ----------------
@app.route("/case/<int:case_id>/chat")
def case_chat(case_id):
    user = current_user()
    if not user:
        return redirect(url_for("login_page"))

    case = db.session.get(Case, case_id)
    if not case or case.user_id != user.id:
        flash("Case not found.")
        return redirect(url_for("home"))

    messages = ChatMessage.query.filter_by(case_id=case.id).order_by(ChatMessage.created_at).all()
    if not messages:
        try:
            opening_text = generate_opening_message(case)
        except Exception:
            app.logger.exception("Gemini opening message failed for case %s", case.id)
            opening_text = (
                "Your case has been saved. I'm having trouble reaching the AI analysis right now — "
                "please refresh in a moment."
            )
        opening = ChatMessage(case_id=case.id, role="model", content=opening_text)
        db.session.add(opening)
        db.session.commit()
        messages = [opening]

    return render_template(
        "case_chat.html",
        active_page="mycases",
        user=user,
        case=case,
        messages=messages,
    )


@app.route("/case/<int:case_id>/chat/message", methods=["POST"])
def case_chat_message(case_id):
    user = current_user()
    if not user:
        return jsonify({"error": "not logged in"}), 401

    case = db.session.get(Case, case_id)
    if not case or case.user_id != user.id:
        return jsonify({"error": "not found"}), 404

    text = (request.get_json(silent=True) or {}).get("message", "").strip()
    if not text:
        return jsonify({"error": "empty message"}), 400

    user_msg = ChatMessage(case_id=case.id, role="user", content=text)
    db.session.add(user_msg)
    db.session.commit()

    all_messages = ChatMessage.query.filter_by(case_id=case.id).order_by(ChatMessage.created_at).all()
    try:
        reply_text = generate_reply(case, all_messages)
    except Exception:
        app.logger.exception("Gemini reply failed for case %s", case.id)
        reply_text = "Sorry, I couldn't reach the AI just now — please try again."

    reply_msg = ChatMessage(case_id=case.id, role="model", content=reply_text)
    db.session.add(reply_msg)
    db.session.commit()

    return jsonify({"reply": reply_text})


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
from flask import Flask, render_template, session, redirect, url_for

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-this-later"


@app.route("/")
def home():
    return render_template("index.html", active_page="home")


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


@app.route("/find-lawyer")
def find_lawyer():
    return "Find a Lawyer page (coming soon)"


@app.route("/issues/<category>")
def issue_category(category):
    return f"Issue category page: {category} (coming soon)"


@app.route("/set-language/<lang>")
def set_language(lang):
    session["current_language"] = lang
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True, port=9000)
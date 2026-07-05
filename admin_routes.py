"""
Minimal CMS for the article library. Gated behind is_admin on the
existing User model — no separate admin login system, just an extra
check on top of your normal session login.
"""
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from functools import wraps

from db import db, User
from articles_models import Article, FeedSource, CATEGORY_META
from rss_ingest import fetch_feed, fetch_all_active_feeds, slugify, unique_slug, sanitize_body, estimate_read_minutes
import json

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _current_user():
    user_id = session.get("user_id")
    return db.session.get(User, user_id) if user_id else None


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _current_user()
        if not user or not getattr(user, "is_admin", False):
            flash("Admin access required.")
            return redirect(url_for("login_page", next=request.path))
        return view(*args, **kwargs)
    return wrapped


# ---------------- Articles ----------------

@admin_bp.route("/articles")
@require_admin
def article_list():
    articles = Article.query.order_by(Article.published_at.desc()).all()
    return render_template("admin/articles.html", articles=articles, category_meta=CATEGORY_META)


@admin_bp.route("/articles/new", methods=["GET", "POST"])
@require_admin
def article_new():
    if request.method == "POST":
        _save_article_from_form(None)
        return redirect(url_for("admin.article_list"))
    return render_template("admin/article_form.html", article=None, category_meta=CATEGORY_META)


@admin_bp.route("/articles/<int:article_id>/edit", methods=["GET", "POST"])
@require_admin
def article_edit(article_id):
    article = Article.query.get_or_404(article_id)
    if request.method == "POST":
        _save_article_from_form(article)
        return redirect(url_for("admin.article_list"))
    return render_template("admin/article_form.html", article=article, category_meta=CATEGORY_META)


@admin_bp.route("/articles/<int:article_id>/delete", methods=["POST"])
@require_admin
def article_delete(article_id):
    article = Article.query.get_or_404(article_id)
    title = article.title
    db.session.delete(article)
    db.session.commit()
    flash(f"Deleted '{title}'.")
    return redirect(url_for("admin.article_list"))


@admin_bp.route("/articles/<int:article_id>/toggle-status", methods=["POST"])
@require_admin
def article_toggle_status(article_id):
    article = Article.query.get_or_404(article_id)
    article.status = "draft" if article.status == "published" else "published"
    db.session.commit()
    return redirect(url_for("admin.article_list"))


def _save_article_from_form(article):
    title = request.form.get("title", "").strip()
    summary = request.form.get("summary", "").strip()
    body_html = sanitize_body(request.form.get("body_html", "").strip())
    category = request.form.get("category", "other")
    image_url = request.form.get("image_url", "").strip() or None
    scenario = request.form.get("scenario", "").strip() or None
    status = request.form.get("status", "published")

    checklist_lines = [l.strip() for l in request.form.get("checklist", "").splitlines() if l.strip()]
    law_lines = [l.strip() for l in request.form.get("relevant_law", "").splitlines() if l.strip()]

    if article is None:
        article = Article(slug=unique_slug(slugify(title)), source_type="manual")
        db.session.add(article)

    article.title = title
    article.summary = summary
    article.body_html = body_html
    article.category = category
    article.image_url = image_url
    article.scenario = scenario
    article.checklist_json = json.dumps(checklist_lines) if checklist_lines else None
    article.relevant_law_json = json.dumps(law_lines) if law_lines else None
    article.status = status
    article.read_time_minutes = estimate_read_minutes(body_html)
    article.updated_at = datetime.utcnow()

    db.session.commit()


# ---------------- Feed sources ----------------

@admin_bp.route("/feeds")
@require_admin
def feed_list():
    feeds = FeedSource.query.order_by(FeedSource.name).all()
    return render_template("admin/feeds.html", feeds=feeds, category_meta=CATEGORY_META)


@admin_bp.route("/feeds/new", methods=["POST"])
@require_admin
def feed_new():
    name = request.form.get("name", "").strip()
    url = request.form.get("url", "").strip()
    default_category = request.form.get("default_category", "other")
    interval = int(request.form.get("fetch_interval_minutes", 60) or 60)

    if not name or not url:
        flash("Feed name and URL are required.")
        return redirect(url_for("admin.feed_list"))
    if FeedSource.query.filter_by(url=url).first():
        flash("That feed URL is already added.")
        return redirect(url_for("admin.feed_list"))

    feed = FeedSource(name=name, url=url, default_category=default_category, fetch_interval_minutes=interval)
    db.session.add(feed)
    db.session.commit()
    flash(f"Added feed '{name}'.")
    return redirect(url_for("admin.feed_list"))


@admin_bp.route("/feeds/<int:feed_id>/toggle-active", methods=["POST"])
@require_admin
def feed_toggle_active(feed_id):
    feed = FeedSource.query.get_or_404(feed_id)
    feed.is_active = not feed.is_active
    db.session.commit()
    return redirect(url_for("admin.feed_list"))


@admin_bp.route("/feeds/<int:feed_id>/delete", methods=["POST"])
@require_admin
def feed_delete(feed_id):
    feed = FeedSource.query.get_or_404(feed_id)
    name = feed.name
    db.session.delete(feed)
    db.session.commit()
    flash(f"Removed feed '{name}'.")
    return redirect(url_for("admin.feed_list"))


@admin_bp.route("/feeds/<int:feed_id>/fetch-now", methods=["POST"])
@require_admin
def feed_fetch_now(feed_id):
    feed = FeedSource.query.get_or_404(feed_id)
    added, error = fetch_feed(feed)
    flash(f"Fetch failed: {error}" if error else f"Fetched '{feed.name}' — {added} new article(s) added.")
    return redirect(url_for("admin.feed_list"))


@admin_bp.route("/feeds/fetch-all", methods=["POST"])
@require_admin
def feed_fetch_all():
    results = fetch_all_active_feeds(only_due=False)
    total = sum(r["added"] for r in results)
    flash(f"Checked {len(results)} feed(s) — {total} new article(s) added.")
    return redirect(url_for("admin.feed_list"))
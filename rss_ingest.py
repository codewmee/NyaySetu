"""
Fetches RSS/Atom feeds and turns new entries into Article rows.
Every entry's HTML is sanitized through bleach before it's stored —
feed content is third-party and untrusted, and gets rendered on a public
page, so this is the one place that absolutely cannot be skipped.
"""

import re
import html
import logging
from datetime import datetime

import feedparser
import bleach

from db import db
from articles_models import Article, FeedSource

logger = logging.getLogger(__name__)

ALLOWED_TAGS = [
    "p",
    "b",
    "strong",
    "i",
    "em",
    "ul",
    "ol",
    "li",
    "a",
    "blockquote",
    "br",
    "h3",
    "h4",
]
ALLOWED_ATTRS = {"a": ["href", "title", "target", "rel"]}


def slugify(text, max_len=90):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:max_len].rstrip("-") or "article"


def unique_slug(base_slug):
    slug = base_slug
    n = 1
    while Article.query.filter_by(slug=slug).first() is not None:
        n += 1
        slug = f"{base_slug}-{n}"
    return slug


def strip_html_to_text(html_str, max_len=280):
    text = re.sub(r"<[^>]+>", " ", html_str or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "…"
    return text


def sanitize_body(html_str):
    return bleach.clean(
        html_str or "", tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True
    )


def estimate_read_minutes(html_str):
    words = len(re.sub(r"<[^>]+>", " ", html_str or "").split())
    return max(1, round(words / 200))


def entry_image(entry):
    if entry.get("media_content"):
        return entry["media_content"][0].get("url")
    if entry.get("media_thumbnail"):
        return entry["media_thumbnail"][0].get("url")
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and "image" in link.get("type", ""):
            return link.get("href")
    return None


def fetch_feed(feed: FeedSource):
    """
    Fetch one feed, insert any entries not already stored (deduped by link).
    Returns (added_count, error_message_or_None). Always updates the feed's
    last_fetched_at / status so the admin panel can show freshness at a glance.
    """
    try:
        parsed = feedparser.parse(feed.url)
    except Exception as exc:
        feed.last_fetched_at = datetime.utcnow()
        feed.last_fetch_status = "error"
        feed.last_fetch_message = str(exc)
        db.session.commit()
        return 0, f"Could not fetch feed: {exc}"

    if parsed.bozo and not parsed.entries:
        message = f"Feed parse error: {parsed.bozo_exception}"
        feed.last_fetched_at = datetime.utcnow()
        feed.last_fetch_status = "error"
        feed.last_fetch_message = message
        db.session.commit()
        return 0, message

    added = 0
    for entry in parsed.entries:
        link = entry.get("link")
        if not link:
            continue
        if Article.query.filter_by(source_url=link).first():
            continue

        title = (entry.get("title") or "Untitled").strip()
        raw_body = (
            entry["content"][0]["value"]
            if entry.get("content")
            else entry.get("summary", "")
        )
        body_html = sanitize_body(raw_body)
        summary = strip_html_to_text(entry.get("summary", raw_body))

        published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        published_at = (
            datetime(*published_struct[:6]) if published_struct else datetime.utcnow()
        )

        article = Article(
            slug=unique_slug(slugify(title)),
            title=title,
            summary=summary or title,
            body_html=body_html or f"<p>{html.escape(summary)}</p>",
            category=feed.default_category,
            image_url=entry_image(entry),
            read_time_minutes=estimate_read_minutes(body_html),
            status="published",
            source_type="rss",
            source_name=feed.name,
            source_url=link,
            feed_id=feed.id,
            published_at=published_at,
        )
        db.session.add(article)
        added += 1

    feed.last_fetched_at = datetime.utcnow()
    feed.last_fetch_status = "ok"
    feed.last_fetch_message = f"{added} new article(s)"
    db.session.commit()
    return added, None


def fetch_all_active_feeds(only_due=False):
    """
    only_due=True is what the hourly scheduler should use — it only hits
    feeds whose own fetch_interval_minutes has actually elapsed, so a feed
    set to "daily" doesn't get re-fetched every time the scheduler ticks.
    A manual "Fetch now" click in the admin panel should call this with
    only_due=False to force it regardless of timing.
    """
    results = []
    feeds = FeedSource.query.filter_by(is_active=True).all()
    for feed in feeds:
        if only_due and not feed.is_due:
            continue
        added, error = fetch_feed(feed)
        results.append({"feed": feed.name, "added": added, "error": error})
    return results

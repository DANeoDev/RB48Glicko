from datetime import datetime, timezone
import re
from flask import Blueprint, request, redirect, url_for, jsonify

from scripts.database.news_database import get_news_connection, get_published_news, add_news_item, publish_news_item
from web.services.ai_service import NewsAIError, format_news_markdown
from web.services.markdown_service import render_markdown, MarkdownError
from web.services.news_service import NewsFileError, create_news_file, read_news_file
from web.services.security import require_admin

news_bp = Blueprint("news", __name__)


def render_news_items(news_items):
    rendered = []
    for news_item in news_items:
        try:
            markdown = read_news_file(news_item["filename"])
            published_at = news_item["published_at"] or news_item["created_at"]
            try:
                entry_date = datetime.fromisoformat(published_at).strftime("%d.%m.%Y")
            except (TypeError, ValueError):
                entry_date = str(published_at).split("T", 1)[0]
            rendered.append({"id": news_item["id"], "html": render_markdown(markdown), "date": entry_date})
        except (NewsFileError, MarkdownError):
            continue
    return rendered


def get_dashboard_news(offset=0, limit=2):
    connection = get_news_connection()
    try:
        published_news = get_published_news(connection, limit=limit, offset=offset)
        next_news = get_published_news(connection, limit=1, offset=offset + limit)
    finally:
        connection.close()
    return render_news_items(published_news), bool(next_news)


def news_filename(markdown, timestamp):
    heading = re.search(r"^#{1,2}\s+(.+?)\s*$", markdown, re.MULTILINE)
    source = heading.group(1) if heading else next((line.strip() for line in markdown.splitlines() if line.strip()), "news")
    source = re.sub(r"[^A-Za-z0-9]+", "-", source).strip("-").lower() or "news"
    return f"{timestamp:%Y%m%d-%H%M%S}-{source}.md"


@news_bp.route("/news/format", methods=["POST"])
@require_admin
def format_news():
    payload = request.get_json(silent=True) or {}
    try:
        markdown = format_news_markdown(payload.get("text", ""))
    except NewsAIError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"markdown": markdown})


@news_bp.route("/news/items")
def get_more_news():
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = min(10, max(1, int(request.args.get("limit", 2))))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid News pagination parameters."}), 400
    news, has_more = get_dashboard_news(offset=offset, limit=limit)
    return jsonify({"news": news, "has_more": has_more})


@news_bp.route("/news/create", methods=["POST"])
@require_admin
def create_news():
    markdown = request.form.get("markdown", "").strip()
    if not markdown:
        return redirect(url_for("stats.home"))
    now = datetime.now(timezone.utc)
    filename = news_filename(markdown, now)
    try:
        create_news_file(filename, markdown)
        connection = get_news_connection()
        try:
            news_id = add_news_item(connection, filename, now.isoformat(timespec="seconds"), None)
            publish_news_item(connection, news_id, now.isoformat(timespec="seconds"))
        finally:
            connection.close()
    except (NewsFileError, OSError):
        return redirect(url_for("stats.home"))
    return redirect(url_for("stats.home"))

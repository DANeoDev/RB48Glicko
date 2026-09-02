from pathlib import Path
import re

from scripts.database.news_database import NEWS_DIRECTORY
from web.services.markdown_service import render_markdown


class NewsFileError(ValueError):
    """Raised when a News Markdown file cannot be safely handled."""


def _safe_filename(filename):
    """Return a safe News filename or raise NewsFileError."""
    if not filename or Path(filename).name != filename:
        raise NewsFileError("Invalid News filename.")

    if not filename.endswith(".md"):
        raise NewsFileError("News files must use the .md extension.")

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*\.md", filename):
        raise NewsFileError("News filename contains invalid characters.")

    return filename


def _news_path(filename):
    """Return the resolved path while guaranteeing it stays in NEWS_DIRECTORY."""
    filename = _safe_filename(filename)
    directory = NEWS_DIRECTORY.resolve()
    path = (directory / filename).resolve()

    if path.parent != directory:
        raise NewsFileError("News file is outside the News directory.")

    return path


def create_news_file(filename, markdown):
    """Create a new Markdown News file and return its path."""
    if not isinstance(markdown, str):
        raise NewsFileError("News content must be text.")

    path = _news_path(filename)
    if path.exists():
        raise NewsFileError("A News file with that filename already exists.")

    NEWS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def read_news_file(filename):
    """Read and return Markdown content from a News file."""
    path = _news_path(filename)
    if not path.is_file():
        raise NewsFileError("News file does not exist.")

    return path.read_text(encoding="utf-8")


def update_news_file(filename, markdown):
    """Replace the Markdown content of an existing News file."""
    if not isinstance(markdown, str):
        raise NewsFileError("News content must be text.")

    path = _news_path(filename)
    if not path.is_file():
        raise NewsFileError("News file does not exist.")

    path.write_text(markdown, encoding="utf-8")
    return path


def delete_news_file(filename):
    """Delete a News Markdown file."""
    path = _news_path(filename)
    if not path.is_file():
        raise NewsFileError("News file does not exist.")

    path.unlink()


def render_news_item(news_item):
    """Read a News item's Markdown file and return safe rendered HTML."""
    markdown = read_news_file(news_item["filename"])
    return render_markdown(markdown)

import html
import re


class MarkdownError(ValueError):
    """Raised when Markdown content cannot be rendered safely."""


def _inline(text):
    """Render the small inline Markdown subset supported by News."""
    text = html.escape(text, quote=False)

    # Links: [label](https://example.com)
    text = re.sub(
        r'\[([^\]]+)\]\((https?://[^\s)]+)\)',
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        text,
    )

    # Bold and italic. Escape has already removed any possibility of raw HTML.
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(r'(?<!_)_([^_\n]+)_(?!_)', r'<em>\1</em>', text)

    return text


def render_markdown(markdown):
    """Convert supported News Markdown into safe HTML.

    Supported syntax:
    - # and ## headings
    - paragraphs
    - **bold** / *italic*
    - unordered lists (-, *, +)
    - ordered lists (1., 2., ...)
    - HTTP(S) links

    Raw HTML is escaped rather than rendered.
    """
    if not isinstance(markdown, str):
        raise MarkdownError("Markdown content must be text.")

    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output = []
    paragraph = []
    list_type = None

    def close_paragraph():
        if paragraph:
            output.append(f'<p>{"<br>".join(paragraph)}</p>')
            paragraph.clear()

    def close_list():
        nonlocal list_type
        if list_type:
            output.append(f"</{list_type}>")
            list_type = None

    for line in lines:
        stripped = line.strip()

        if not stripped:
            close_paragraph()
            close_list()
            continue

        heading = re.match(r'^(#{1,2})\s+(.+?)\s*#*$', stripped)
        if heading:
            close_paragraph()
            close_list()
            level = len(heading.group(1))
            output.append(f'<h{level}>{_inline(heading.group(2))}</h{level}>')
            continue

        unordered = re.match(r'^[-+*]\s+(.+)$', stripped)
        ordered = re.match(r'^\d+[.)]\s+(.+)$', stripped)

        if unordered or ordered:
            close_paragraph()
            wanted_type = "ul" if unordered else "ol"
            if list_type != wanted_type:
                close_list()
                output.append(f"<{wanted_type}>")
                list_type = wanted_type
            item = unordered.group(1) if unordered else ordered.group(1)
            output.append(f'<li>{_inline(item)}</li>')
            continue

        close_list()
        paragraph.append(_inline(stripped))

    close_paragraph()
    close_list()

    return "\n".join(output)

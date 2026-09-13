from __future__ import annotations

from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

INLINE_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code",
    "mark", "sub", "sup", "tg-spoiler", "a", "tg-emoji", "tg-time", "tg-math", "br",
}


class _InlineSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []

    def _safe_href(self, value: str) -> str | None:
        raw = (value or "").strip()
        if raw.startswith("#"):
            return raw
        parsed = urlparse(raw)
        if parsed.scheme.lower() in {"http", "https", "mailto", "tel", "tg"}:
            return raw
        return None

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in {"div", "p"}:
            if self.parts and not self.parts[-1].endswith("<br>"):
                self.parts.append("<br>")
            self.stack.append("")
            return
        if tag not in INLINE_TAGS:
            self.stack.append("")
            return
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        rendered = ""
        if tag == "a":
            href = self._safe_href(values.get("href", ""))
            name = values.get("name", "").strip()
            if href:
                rendered = f'<a href="{escape(href, quote=True)}">'
            elif name and all(ch.isalnum() or ch in "_-" for ch in name):
                rendered = f'<a name="{escape(name, quote=True)}">'
            else:
                self.stack.append("")
                return
        elif tag == "tg-emoji":
            emoji_id = values.get("emoji-id", "")
            if emoji_id.isdigit():
                rendered = f'<tg-emoji emoji-id="{emoji_id}">'
            else:
                self.stack.append("")
                return
        elif tag == "tg-time":
            unix = values.get("unix", "")
            fmt = values.get("format", "")
            if unix.lstrip("-").isdigit():
                rendered = f'<tg-time unix="{unix}"'
                if fmt:
                    rendered += f' format="{escape(fmt, quote=True)}"'
                rendered += ">"
            else:
                self.stack.append("")
                return
        elif tag == "br":
            self.parts.append("<br>")
            self.stack.append("")
            return
        else:
            rendered = f"<{tag}>"
        self.parts.append(rendered)
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs):
        if tag.lower() == "br":
            self.parts.append("<br>")

    def handle_endtag(self, tag: str):
        if not self.stack:
            return
        opened = self.stack.pop()
        if opened:
            self.parts.append(f"</{opened}>")

    def handle_data(self, data: str):
        self.parts.append(escape(data, quote=False))

    def close(self):
        super().close()
        while self.stack:
            opened = self.stack.pop()
            if opened:
                self.parts.append(f"</{opened}>")


def sanitize_inline_html(value: str) -> str:
    parser = _InlineSanitizer()
    parser.feed(str(value or ""))
    parser.close()
    return "".join(parser.parts)

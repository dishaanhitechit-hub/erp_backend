# app/utils/html_sanitize.py
"""
Allow-list HTML sanitizer for small rich-text fields (bold, italic, lists, links).
Stdlib only. Anything not listed is dropped: unknown tags lose their markup but
keep their text; <script>/<style>/... lose their content too; all attributes
are dropped except a safe href on <a>.
"""

from html import escape
from html.parser import HTMLParser

ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "s", "strike", "del", "p", "br", "div", "span",
    "ul", "ol", "li", "a", "h1", "h2", "h3", "h4", "blockquote", "code", "pre", "hr",
}
VOID_TAGS = {"br", "hr"}
DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math", "head", "title"}
SAFE_SCHEMES = ("http://", "https://", "mailto:")


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.open = []       # stack of allowed tags currently open
        self.skip = 0        # depth inside a DROP_CONTENT tag

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED_TAGS:
            return
        if tag == "a":
            href = next((v for k, v in attrs if k.lower() == "href" and v), "")
            href = href.strip()
            if href.lower().startswith(SAFE_SCHEMES):
                self.out.append(f'<a href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer">')
            else:
                self.out.append("<a>")
        else:
            self.out.append(f"<{tag}>")
        if tag not in VOID_TAGS:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in VOID_TAGS and not self.skip:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in self.open:
            return
        # close everything opened after it too, so output stays well-formed
        while self.open:
            t = self.open.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))

    def result(self):
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def sanitize_html(value):
    if not value:
        return ""
    p = _Sanitizer()
    p.feed(str(value))
    p.close()
    return p.result().strip()


def html_to_text(value):
    """Plain text of an HTML string (used to reject bodies that are empty once tags are removed)."""
    class _T(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []

        def handle_data(self, d):
            self.parts.append(d)
    t = _T()
    t.feed(value or "")
    t.close()
    return "".join(t.parts).replace("\xa0", " ").strip()

"""HTML sanitisation helpers for LLM/operator-generated content.

The website generator intentionally creates rich single-file HTML, so we do not
try to reduce it to a tiny email-style allowlist. We do, however, strip active
content primitives that turn prompt injection into script execution: <script>,
event-handler attributes, javascript:/data: script URLs, iframes/objects, and
meta refresh.
"""

import re

_SCRIPT_BLOCK_RE = re.compile(r'<\s*(script|iframe|object|embed|applet|base)\b[^>]*>.*?<\s*/\s*\1\s*>', re.IGNORECASE | re.DOTALL)
_SELF_CLOSING_ACTIVE_RE = re.compile(r'<\s*(script|iframe|object|embed|applet|base|meta)\b[^>]*(?:/\s*)?>', re.IGNORECASE | re.DOTALL)
_EVENT_ATTR_RE = re.compile(r'\s+on[a-zA-Z0-9_:-]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE)
_DANGEROUS_URL_ATTR_RE = re.compile(
    r'\s+(href|src|xlink:href|formaction|action)\s*=\s*("\s*(?:javascript|data:text/html)\s*:[^"]*"|\'\s*(?:javascript|data:text/html)\s*:[^\']*\'|\s*(?:javascript|data:text/html)\s*:[^\s>]+)',
    re.IGNORECASE,
)
_SRC_DOC_RE = re.compile(r'\s+srcdoc\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE | re.DOTALL)
_META_REFRESH_RE = re.compile(r'<\s*meta\b[^>]*http-equiv\s*=\s*("|\')?refresh\1?[^>]*>', re.IGNORECASE | re.DOTALL)


def strip_active_html(html):
    """Remove active-content primitives while preserving static layout/CSS."""
    if not html:
        return ''
    cleaned = str(html)
    cleaned = _SCRIPT_BLOCK_RE.sub('', cleaned)
    cleaned = _META_REFRESH_RE.sub('', cleaned)
    cleaned = _SELF_CLOSING_ACTIVE_RE.sub('', cleaned)
    cleaned = _EVENT_ATTR_RE.sub('', cleaned)
    cleaned = _DANGEROUS_URL_ATTR_RE.sub('', cleaned)
    cleaned = _SRC_DOC_RE.sub('', cleaned)
    return cleaned


def sanitize_email_html(html):
    """Sanitize phishing email HTML before storing/pushing to GoPhish."""
    if not html:
        return ''
    try:
        import bleach
        allowed_tags = [
            'a', 'abbr', 'acronym', 'b', 'blockquote', 'br', 'code', 'div', 'em',
            'h1', 'h2', 'h3', 'h4', 'hr', 'i', 'img', 'li', 'ol', 'p', 'pre',
            'span', 'strong', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead',
            'tr', 'ul', 'u'
        ]
        allowed_attrs = {
            '*': ['class', 'style'],
            'a': ['href', 'title', 'target', 'rel'],
            'img': ['src', 'alt', 'title', 'width', 'height'],
            'td': ['colspan', 'rowspan'],
            'th': ['colspan', 'rowspan'],
        }
        cleaned = bleach.clean(
            str(html),
            tags=allowed_tags,
            attributes=allowed_attrs,
            protocols=['http', 'https', 'mailto'],
            strip=True,
        )
    except Exception:
        cleaned = strip_active_html(html)
    return strip_active_html(cleaned)

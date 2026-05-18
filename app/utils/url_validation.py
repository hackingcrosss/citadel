"""Centralised URL / hostname validation helpers.

Used by credential-save endpoints and outbound-HTTP adapters to block
SSRF (E-1), path-traversal (D-01), and similar injection classes.
"""

import ipaddress
import re
import socket
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Hostname / domain validation
# ---------------------------------------------------------------------------

# RFC-952 + RFC-1123 label: alphanumeric + hyphens, no leading/trailing hyphen
_DOMAIN_RE = re.compile(
    r'^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?$',
    re.IGNORECASE,
)


def is_valid_domain(name):
    """Return True if *name* looks like a valid domain (no path, no port)."""
    if not name or len(name) > 253:
        return False
    return bool(_DOMAIN_RE.match(name))


# ---------------------------------------------------------------------------
# SSRF-safe URL validation
# ---------------------------------------------------------------------------

# Blocked IP ranges — loopback, link-local, private, CGNAT, metadata, etc.
_BLOCKED_NETS = [
    ipaddress.ip_network('0.0.0.0/8'),
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('100.64.0.0/10'),
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.0.0.0/24'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('198.18.0.0/15'),
    # IPv6
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('fc00::/7'),
    ipaddress.ip_network('fe80::/10'),
]


def _is_blocked_ip(ip_str):
    """Return True if *ip_str* resolves to a blocked network."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in net for net in _BLOCKED_NETS)


def validate_outbound_url(url, *, resolve=True, allow_schemes=('http', 'https')):
    """Validate a URL for outbound use.  Returns (ok, error_message).

    Checks:
    - Scheme is in *allow_schemes*.
    - Hostname is present and contains no user-info (``user:pass@``).
    - If *resolve* is True, resolves the hostname and rejects blocked IPs
      (loopback, RFC1918, link-local, metadata, CGNAT).
    - Rejects bare IP addresses that fall in blocked ranges even without
      resolution.

    Returns ``(True, None)`` on success, ``(False, 'reason')`` on failure.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, 'Malformed URL'

    if parsed.scheme not in allow_schemes:
        return False, f'Scheme must be one of {", ".join(allow_schemes)}'

    host = parsed.hostname
    if not host:
        return False, 'Missing hostname'

    # Reject user-info (user:pass@ in URL)
    if parsed.username or parsed.password:
        return False, 'URL must not contain user credentials'

    # IP / DNS resolution checks — only when resolve=True
    if resolve:
        # Check if host is a literal IP in a blocked range
        if _is_blocked_ip(host):
            return False, f'Host {host} resolves to a blocked address'
        try:
            results = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for family, _, _, _, sockaddr in results:
                ip_str = sockaddr[0]
                if _is_blocked_ip(ip_str):
                    return False, f'Host {host} resolves to blocked address {ip_str}'
        except socket.gaierror:
            # Can't resolve — allow through (the actual request will fail).
            pass

    return True, None


# ---------------------------------------------------------------------------
# nginx config safe-value validation (D-02)
# ---------------------------------------------------------------------------

_BACKEND_SAFE_RE = re.compile(r'^[A-Za-z0-9_$.:/@-]+$')


def is_safe_nginx_backend(value):
    """Return True if *value* is safe to interpolate into an nginx proxy_pass.

    Rejects newlines, carriage returns, null bytes, quotes, semicolons,
    braces, and any character outside a strict allowlist.
    """
    if not value:
        return False
    if any(c in value for c in ('\n', '\r', '\0', '"', "'", ';', '{', '}')):
        return False
    return bool(_BACKEND_SAFE_RE.match(value))

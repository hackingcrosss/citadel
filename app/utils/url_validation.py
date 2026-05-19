"""Centralised URL / hostname validation helpers.

Used by credential-save endpoints and outbound-HTTP adapters to block
SSRF (E-1), path-traversal (D-01), and similar injection classes.
"""

import ipaddress
import os
import posixpath
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


def _is_blocked_docker_ip(ip_str):
    """Return True for Docker daemon targets that should never be remote.

    Unlike generic SSRF checks, explicit remote Docker administration often
    targets RFC1918 addresses. Allow private ranges after the admin opt-in, but
    continue blocking loopback, link-local/metadata, multicast, unspecified,
    and reserved addresses.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any((
        addr.is_loopback,
        addr.is_link_local,
        addr.is_multicast,
        addr.is_unspecified,
        addr.is_reserved,
    ))


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
# Provider-specific URL/path validators
# ---------------------------------------------------------------------------

_OPENAI_AZURE_SUFFIXES = ('.openai.azure.com', '.cognitive.microsoft.com')
_OPENAI_ALLOWED_EXACT = {'api.openai.com'}


def validate_openai_endpoint(url):
    """Validate an OpenAI/Azure OpenAI endpoint before it reaches the SDK.

    Allowed endpoints are intentionally narrow: the public OpenAI API and
    Azure-owned OpenAI/Cognitive Services hosts over HTTPS. This closes the
    admin-configurable endpoint SSRF/proxy primitive while still supporting
    the two deployment modes the application documents.
    """
    ok, reason = validate_outbound_url(url, resolve=True, allow_schemes=('https',))
    if not ok:
        return ok, reason

    parsed = urlparse(url)
    host = (parsed.hostname or '').lower().rstrip('.')
    if host in _OPENAI_ALLOWED_EXACT:
        if parsed.path not in ('', '/', '/v1', '/v1/'):
            return False, 'OpenAI endpoint path must be /v1 or empty'
        return True, None

    if host.endswith(_OPENAI_AZURE_SUFFIXES):
        if parsed.path not in ('', '/'):
            return False, 'Azure OpenAI endpoint must not include a path'
        return True, None

    return False, 'OpenAI endpoint host must be api.openai.com, *.openai.azure.com, or *.cognitive.microsoft.com'


_DOCKER_ALLOWED_LOCAL_SOCKET = 'unix:///var/run/docker.sock'


def validate_docker_host(base_url, *, allow_remote=None):
    """Validate Docker SDK base_url values.

    By default only the canonical local Docker socket is accepted. Remote
    daemon access is a dangerous administrative exception and must be enabled
    explicitly either in Settings → Docker or with
    CITADEL_ALLOW_REMOTE_DOCKER=true; when enabled it must use TLS on the
    conventional 2376 port.
    """
    if not base_url or not str(base_url).strip():
        return True, None
    value = str(base_url).strip()
    if value == _DOCKER_ALLOWED_LOCAL_SOCKET:
        return True, None

    if allow_remote is None:
        allow_remote = os.getenv('CITADEL_ALLOW_REMOTE_DOCKER', '').lower() in ('1', 'true', 'yes')
    if not allow_remote:
        return False, 'Remote Docker hosts are disabled; use unix:///var/run/docker.sock or enable Settings → Docker → Allow remote Docker hosts'

    parsed = urlparse(value)
    if parsed.scheme not in ('tcp', 'https'):
        return False, 'Remote Docker host must use tcp://host:2376 or https://host:2376 with TLS'
    if parsed.username or parsed.password:
        return False, 'Docker host must not contain credentials'
    if not parsed.hostname:
        return False, 'Docker host is missing hostname'
    if parsed.scheme == 'tcp' and parsed.port != 2376:
        return False, 'tcp:// Docker hosts must use TLS port 2376'
    if parsed.scheme == 'https' and parsed.port not in (None, 2376):
        return False, 'https:// Docker hosts must use port 2376 if a port is specified'
    if _is_blocked_docker_ip(parsed.hostname):
        return False, 'Docker host resolves to a blocked address'
    try:
        for _family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(parsed.hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM):
            if _is_blocked_docker_ip(sockaddr[0]):
                return False, f'Docker host resolves to blocked address {sockaddr[0]}'
    except socket.gaierror:
        pass
    return True, None


_DEPLOY_PATH_BLOCKLIST = ('/etc', '/proc', '/sys', '/dev', '/run', '/boot', '/root', '/usr', '/bin', '/sbin', '/lib', '/lib64', '/var/lib', '/var/run')


def validate_npm_deploy_path(path):
    """Validate the remote NPM website deploy path.

    The deploy path is later used over SSH/SFTP. Keep it absolute, normalized,
    and away from sensitive system locations so a misconfigured/compromised
    admin cannot redirect website generation into OS/config directories.
    """
    if not path or not str(path).strip():
        return False, 'Deploy path is required'
    value = str(path).strip()
    if '\x00' in value or '\n' in value or '\r' in value:
        return False, 'Deploy path contains control characters'
    if not value.startswith('/'):
        return False, 'Deploy path must be absolute'
    normalized = posixpath.normpath(value)
    if normalized in ('/', '.'):
        return False, 'Deploy path must not be filesystem root'
    if normalized != value.rstrip('/'):
        return False, 'Deploy path must be normalized and must not contain .. segments'
    for blocked in _DEPLOY_PATH_BLOCKLIST:
        if normalized == blocked or normalized.startswith(blocked + '/'):
            return False, f'Deploy path must not be under {blocked}'
    if not normalized.startswith('/var/www/') and normalized != '/var/www/html':
        return False, 'Deploy path must be under /var/www/'
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

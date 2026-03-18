"""
Malleable C2 profile parser and Nginx config generator.

Parses Cobalt Strike Malleable C2 profiles to extract traffic indicators
(URIs, headers, parameters, user agents) and generates Nginx location
blocks that restrict reverse-proxy traffic to only allow matching C2 comms.
"""

import re


# ---------------------------------------------------------------------------
# Tokeniser — strips comments, then yields tokens one at a time
# ---------------------------------------------------------------------------

def _strip_comments(text):
    """Remove single-line # comments (not inside strings)."""
    out = []
    for line in text.splitlines():
        in_str = False
        for i, ch in enumerate(line):
            if ch == '"' and (i == 0 or line[i - 1] != '\\'):
                in_str = not in_str
            elif ch == '#' and not in_str:
                line = line[:i]
                break
        out.append(line)
    return '\n'.join(out)


_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|[{}();]|[^\s{}();\"]+')


def _tokenize(text):
    text = _strip_comments(text)
    return _TOKEN_RE.findall(text)


def _unquote(s):
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"').replace('\\\\', '\\')
    return s


# ---------------------------------------------------------------------------
# Recursive-descent parser — builds a simple AST
# ---------------------------------------------------------------------------

def _parse_block(tokens, pos):
    """Parse a { ... } block, returning (dict_of_contents, new_pos).

    The dict maps:
      'set:<key>'      -> value string
      'header:<value>' -> header-name (for repeated 'header' directives)
      'parameter:<val>'-> parameter-name
      'block:<name>'   -> nested dict (for client, server, metadata, id, output)
      'uri_list'       -> [uri, ...] from 'set uri' split on space
    """
    result = {'_headers': [], '_parameters': []}
    while pos < len(tokens):
        tok = tokens[pos]

        if tok == '}':
            return result, pos + 1

        if tok == ';':
            pos += 1
            continue

        # 'set' directive: set key "value";
        if tok == 'set' and pos + 2 < len(tokens):
            key = tokens[pos + 1]
            val = _unquote(tokens[pos + 2])
            result[f'set:{key}'] = val
            pos += 3
            # skip optional semicolon
            if pos < len(tokens) and tokens[pos] == ';':
                pos += 1
            continue

        # 'header' directive: header "Name" "Value";
        if tok == 'header' and pos + 2 < len(tokens):
            name = _unquote(tokens[pos + 1])
            value = _unquote(tokens[pos + 2])
            result['_headers'].append((name, value))
            pos += 3
            if pos < len(tokens) and tokens[pos] == ';':
                pos += 1
            continue

        # 'parameter' directive: parameter "name" "value";
        if tok == 'parameter' and pos + 2 < len(tokens):
            name = _unquote(tokens[pos + 1])
            value = _unquote(tokens[pos + 2])
            result['_parameters'].append((name, value))
            pos += 3
            if pos < len(tokens) and tokens[pos] == ';':
                pos += 1
            continue

        # Data transform keywords (base64, mask, append, prepend, etc.) — skip
        if tok in ('base64', 'base64url', 'mask', 'netbios', 'netbiosu', 'print',
                   'uri-append', 'strrep'):
            pos += 1
            # strrep has two string args
            if tok == 'strrep' and pos + 1 < len(tokens):
                pos += 2
            if pos < len(tokens) and tokens[pos] == ';':
                pos += 1
            continue

        # 'append' / 'prepend' with a string arg
        if tok in ('append', 'prepend') and pos + 1 < len(tokens):
            pos += 2
            if pos < len(tokens) and tokens[pos] == ';':
                pos += 1
            continue

        # Sub-block: name { ... }
        if pos + 1 < len(tokens) and tokens[pos + 1] == '{':
            block_name = tok
            inner, new_pos = _parse_block(tokens, pos + 2)
            result[f'block:{block_name}'] = inner
            pos = new_pos
            continue

        # Skip unknown tokens
        pos += 1

    return result, pos


def _parse_top_level(tokens):
    """Parse top-level: global 'set' directives and named blocks."""
    result = {'_global': {}, '_blocks': {}}
    pos = 0
    while pos < len(tokens):
        tok = tokens[pos]

        if tok == ';':
            pos += 1
            continue

        # Global 'set' directive
        if tok == 'set' and pos + 2 < len(tokens):
            key = tokens[pos + 1]
            val = _unquote(tokens[pos + 2])
            result['_global'][key] = val
            pos += 3
            if pos < len(tokens) and tokens[pos] == ';':
                pos += 1
            continue

        # Top-level block: http-get { ... }, http-post { ... }, etc.
        if pos + 1 < len(tokens) and tokens[pos + 1] == '{':
            block_name = tok
            inner, new_pos = _parse_block(tokens, pos + 2)
            # Some blocks can appear with a variant name like http-get "variant"
            result['_blocks'][block_name] = inner
            pos = new_pos
            continue

        # Top-level block with variant: http-get "variant" { ... }
        if (pos + 2 < len(tokens) and tokens[pos + 1].startswith('"')
                and tokens[pos + 2] == '{'):
            block_name = tok
            _variant = _unquote(tokens[pos + 1])
            inner, new_pos = _parse_block(tokens, pos + 3)
            # Store with variant suffix
            result['_blocks'][f'{block_name}:{_variant}'] = inner
            pos = new_pos
            continue

        pos += 1

    return result


# ---------------------------------------------------------------------------
# Extract traffic indicators from the AST
# ---------------------------------------------------------------------------

def parse_profile(profile_text):
    """Parse a Malleable C2 profile and extract traffic-defining indicators.

    Returns a dict with:
      user_agent: str
      http_get: {uris: [...], client_headers: [...], client_parameters: [...]}
      http_post: {uris: [...], client_headers: [...], client_parameters: [...]}
      http_stager: {uri_x86: str, uri_x64: str, client_headers: [...]}
      http_config: {headers: [...], trust_x_forwarded_for: str}
      global_options: {key: value, ...}
      raw_blocks: [block_name, ...]
    """
    tokens = _tokenize(profile_text)
    ast = _parse_top_level(tokens)

    result = {
        'user_agent': ast['_global'].get('useragent', ''),
        'http_get': _extract_http_block(ast['_blocks'], 'http-get'),
        'http_post': _extract_http_block(ast['_blocks'], 'http-post'),
        'http_stager': _extract_stager_block(ast['_blocks']),
        'http_config': _extract_http_config(ast['_blocks']),
        'global_options': ast['_global'],
        'raw_blocks': list(ast['_blocks'].keys()),
    }
    return result


def _extract_http_block(blocks, block_name):
    """Extract URIs, headers, and parameters from an http-get or http-post block."""
    # Find the block (may have variant suffix)
    block = None
    for key, val in blocks.items():
        if key == block_name or key.startswith(block_name + ':'):
            block = val
            break

    if not block:
        return {'uris': [], 'client_headers': [], 'client_parameters': []}

    # URIs from 'set uri'
    uri_str = block.get('set:uri', '')
    uris = [u.strip() for u in uri_str.split() if u.strip()] if uri_str else []

    # Client sub-block
    client = block.get('block:client', {})
    client_headers = client.get('_headers', [])
    client_params = client.get('_parameters', [])

    # Also check for metadata/id/output sub-blocks for header/parameter directives
    for sub_name in ('block:metadata', 'block:id', 'block:output'):
        sub = client.get(sub_name, {})
        if sub:
            client_headers.extend(sub.get('_headers', []))
            client_params.extend(sub.get('_parameters', []))

    return {
        'uris': uris,
        'client_headers': client_headers,
        'client_parameters': client_params,
    }


def _extract_stager_block(blocks):
    """Extract http-stager URIs and headers."""
    block = None
    for key, val in blocks.items():
        if key == 'http-stager' or key.startswith('http-stager:'):
            block = val
            break

    if not block:
        return {'uri_x86': '', 'uri_x64': '', 'client_headers': []}

    client = block.get('block:client', {})
    return {
        'uri_x86': block.get('set:uri_x86', ''),
        'uri_x64': block.get('set:uri_x64', ''),
        'client_headers': client.get('_headers', []),
    }


def _extract_http_config(blocks):
    """Extract http-config headers and settings."""
    block = blocks.get('http-config', {})
    if not block:
        return {'headers': [], 'trust_x_forwarded_for': ''}

    # 'set headers' is a comma-separated list of response header names to keep
    headers_str = block.get('set:headers', '')
    headers = [h.strip() for h in headers_str.split(',') if h.strip()] if headers_str else []

    return {
        'headers': headers,
        'trust_x_forwarded_for': block.get('set:trust_x_forwarded_for', ''),
    }


# ---------------------------------------------------------------------------
# Nginx config generator
# ---------------------------------------------------------------------------

def generate_nginx_config(parsed, backend='$forward_scheme://$server:$port'):
    """Generate an Nginx config snippet that restricts traffic to match the
    C2 profile.  Designed for use in NPM's Advanced configuration tab.

    The generated config:
      - Whitelists only the URIs from http-get, http-post, and http-stager
      - Validates User-Agent if set in the profile
      - Checks for required client headers
      - Returns 404 for non-matching requests (blends in as a normal web server)
      - Proxies matching requests to the backend
    """
    ua = parsed.get('user_agent', '')
    http_get = parsed.get('http_get', {})
    http_post = parsed.get('http_post', {})
    http_stager = parsed.get('http_stager', {})

    # Collect all allowed URIs
    all_uris = []
    get_uris = http_get.get('uris', [])
    post_uris = http_post.get('uris', [])
    stager_uris = []
    if http_stager.get('uri_x86'):
        stager_uris.append(http_stager['uri_x86'])
    if http_stager.get('uri_x64'):
        stager_uris.append(http_stager['uri_x64'])
    all_uris = get_uris + post_uris + stager_uris

    # Collect all required client headers (from http-get and http-post)
    get_headers = http_get.get('client_headers', [])
    post_headers = http_post.get('client_headers', [])

    # Build conditions — we use a scoring map variable approach
    lines = []
    lines.append('# =============================================================')
    lines.append('# Nginx C2 Restrictor — auto-generated from Malleable C2 profile')
    lines.append('# Only allows traffic matching the C2 profile; everything else')
    lines.append('# gets a 404 to blend in as a normal web server.')
    lines.append('# =============================================================')
    lines.append('')

    if not all_uris:
        lines.append('# WARNING: No URIs found in profile. Cannot generate restrictions.')
        lines.append('# Make sure the profile defines http-get { set uri "..."; }')
        return '\n'.join(lines)

    # --- User-Agent check ---
    if ua:
        escaped_ua = _nginx_escape_regex(ua)
        lines.append('# Block requests with wrong User-Agent')
        lines.append(f'if ($http_user_agent !~* "^{escaped_ua}$") {{')
        lines.append('    return 404;')
        lines.append('}')
        lines.append('')

    # --- URI-based location blocks ---
    # We generate a default deny, then allow specific URIs
    lines.append('# ----- Default: deny everything not matching C2 URIs -----')
    lines.append('# (Place this in the NPM Advanced tab for the proxy host,')
    lines.append('#  or as a server-level snippet.)')
    lines.append('')

    # Generate location blocks for GET URIs
    if get_uris:
        lines.append('# --- http-get URIs (beacon check-in / tasking) ---')
        for uri in get_uris:
            _add_location_block(lines, uri, 'GET', get_headers, backend)
        lines.append('')

    # Generate location blocks for POST URIs
    if post_uris:
        lines.append('# --- http-post URIs (beacon data submission) ---')
        for uri in post_uris:
            _add_location_block(lines, uri, 'POST', post_headers, backend)
        lines.append('')

    # Generate location blocks for stager URIs
    if stager_uris:
        lines.append('# --- http-stager URIs (initial payload delivery) ---')
        stager_headers = http_stager.get('client_headers', [])
        for uri in stager_uris:
            _add_location_block(lines, uri, 'GET', stager_headers, backend)
        lines.append('')

    # Catch-all: deny everything else
    lines.append('# --- Catch-all: return 404 for non-C2 traffic ---')
    lines.append('location / {')
    lines.append('    return 404;')
    lines.append('}')

    return '\n'.join(lines)


def _add_location_block(lines, uri, method, headers, backend):
    """Add a single nginx location block for a C2 URI."""
    # Normalize URI
    uri = uri.strip()
    if not uri.startswith('/'):
        uri = '/' + uri

    lines.append(f'location = {uri} {{')

    # Method restriction
    lines.append(f'    limit_except {method} {{')
    lines.append('        deny all;')
    lines.append('    }')

    # Header checks — use if directives for required headers
    for hdr_name, hdr_value in headers:
        # Skip common headers that aren't useful for filtering
        if hdr_name.lower() in ('host', 'connection', 'content-length',
                                 'content-type', 'accept-encoding'):
            continue
        var_name = 'http_' + hdr_name.lower().replace('-', '_')
        if hdr_value:
            escaped_val = _nginx_escape_regex(hdr_value)
            lines.append(f'    if (${var_name} !~* "^{escaped_val}$") {{')
            lines.append('        return 404;')
            lines.append('    }')
        else:
            # Just check the header exists
            lines.append(f'    if (${var_name} = "") {{')
            lines.append('        return 404;')
            lines.append('    }')

    # Proxy pass
    lines.append(f'    proxy_pass {backend};')
    lines.append('    proxy_set_header Host $host;')
    lines.append('    proxy_set_header X-Real-IP $remote_addr;')
    lines.append('    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;')
    lines.append('}')


def _nginx_escape_regex(s):
    """Escape special regex characters for use in nginx regex."""
    special = r'\.+*?^${}()|[]/'
    out = []
    for ch in s:
        if ch in special:
            out.append('\\')
        out.append(ch)
    return ''.join(out)

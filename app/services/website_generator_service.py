import io
import json
import random
import re
import shlex
import string
import yaml
from app.services.openai_service import get_client as _get_client

_EXTRA_CONTEXT_MAX = 500


def generate_website_plan(category, domain=None, extra_context=None):
    """Call the model to produce a structured JSON website plan for the given business category."""
    client, deployment = _get_client()

    domain_hint = ''
    if domain:
        domain_hint = f"""
The website will be hosted at **https://{domain}**.
- The business name should feel natural alongside the domain "{domain}" (it can match, complement, or be inspired by it)
- Use contact@{domain} (or a role-appropriate variant like support@{domain}) as the contact email
- The footer address and phone should feel consistent with a business that owns this domain
"""

    extra_hint = ''
    if extra_context and extra_context.strip():
        sanitized_extra = extra_context.strip()[:_EXTRA_CONTEXT_MAX]
        extra_hint = f"""
Design preferences:
{sanitized_extra}
"""

    planning_prompt = f"""You are a creative web designer creating a website for a business in the {category} industry.
{domain_hint}{extra_hint}
Generate a comprehensive website plan including:

1. **Brand Identity**
   - Business name (creative, memorable, consistent with the domain if provided)
   - Tagline/slogan
   - Color palette (4-6 colors with hex codes)
   - Font recommendations (2-3 fonts from Google Fonts)
   - Overall aesthetic direction (be specific and creative)

2. **Content Strategy**
   - Hero section headline and subheadline
   - 3-4 key value propositions
   - About section content (2-3 paragraphs)
   - 4-6 services/features to highlight
   - Call-to-action text
   - Footer information (use the domain-based email if a domain was provided)

3. **Design Direction**
   - Choose a bold, distinctive aesthetic that fits the industry
   - Describe the visual style (modern minimal, brutalist, editorial, retro-futuristic, organic, luxury, etc.)
   - Key design elements to include
   - Animation/interaction ideas

Return your response as valid JSON with this structure:
{{
  "brand": {{
    "name": "string",
    "tagline": "string",
    "colors": {{"primary": "#hex", "secondary": "#hex", "accent": "#hex", "background": "#hex", "text": "#hex"}},
    "fonts": {{"display": "Font Name", "body": "Font Name"}},
    "aesthetic": "detailed description"
  }},
  "content": {{
    "hero": {{"headline": "string", "subheadline": "string"}},
    "valueProps": ["string", "string", "string"],
    "about": "multi-paragraph string",
    "services": [{{"title": "string", "description": "string"}}],
    "cta": "string",
    "footer": {{"email": "string", "phone": "string", "address": "string"}}
  }},
  "design": {{
    "style": "string",
    "keyElements": ["string", "string"],
    "interactions": "string"
  }}
}}

Make this unique and tailored specifically to {category}. Avoid generic, cookie-cutter designs.{extra_hint}"""

    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": planning_prompt}],
        max_tokens=4000,
        temperature=0.7,
    )

    content = response.choices[0].message.content
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if not json_match:
        raise ValueError('Model did not return valid JSON for the website plan')
    return json.loads(json_match.group())


def generate_html(plan, category, domain=None, extra_context=None):
    """Call the model to produce the full single-file HTML website."""
    client, deployment = _get_client()

    domain_instructions = ''
    if domain:
        domain_instructions = f"""
Domain & branding requirements (IMPORTANT — apply these exactly):
- The website is hosted at: https://{domain}
- Set <title> to the brand name: {plan['brand']['name']}
- Include <link rel="canonical" href="https://{domain}"> in <head>
- Set Open Graph meta tags: og:url="https://{domain}", og:site_name="{plan['brand']['name']}"
- Navigation logo / wordmark must display: {plan['brand']['name']}
- Footer contact email must be: {plan['content']['footer'].get('email', 'contact@' + domain)}
- Any "mailto:" links must use: {plan['content']['footer'].get('email', 'contact@' + domain)}
- The copyright line in the footer must read: © {plan['brand']['name']}
- Do NOT hardcode any other domain, placeholder URL, or example.com anywhere in the page
"""

    code_prompt = f"""Create a complete, production-ready single-page website based on this plan:

{json.dumps(plan, indent=2)}

Industry: {category}
{domain_instructions}
Requirements:
1. Single HTML file with embedded CSS and JavaScript
2. Fully responsive (mobile-first)
3. Modern, semantic HTML5
4. High-quality aesthetic following the design direction
5. Smooth animations and micro-interactions
6. Professional typography and spacing
7. Functional contact form (frontend validation only)
8. SEO-friendly meta tags
9. Accessibility features (ARIA labels, semantic markup)
10. Performance-optimized (efficient CSS, minimal dependencies)

Design principles from the plan:
- Aesthetic: {plan['design']['style']}
- Key elements: {', '.join(plan['design']['keyElements'])}
- Interactions: {plan['design']['interactions']}

Include:
- Navigation menu
- Hero section with the headline and CTA
- About section
- Services/Features section (grid or cards)
- Contact section with form
- Footer

Use Google Fonts for: {plan['brand']['fonts']['display']} and {plan['brand']['fonts']['body']}

Color palette:
{json.dumps(plan['brand']['colors'], indent=2)}

Make this production-grade, visually striking, and unique. Avoid generic AI aesthetics.
Use creative layouts, unexpected typography choices, engaging animations.
{('Design preferences: ' + extra_context.strip()[:_EXTRA_CONTEXT_MAX]) if extra_context and extra_context.strip() else ''}
Return ONLY the complete HTML code, no explanations."""

    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": code_prompt}],
        temperature=0.7,
    )

    return response.choices[0].message.content


def clean_html(html_text):
    """Strip markdown code fences from the model response."""
    if not html_text:
        return ''
    html_text = re.sub(r'^```html\s*\n', '', html_text, flags=re.MULTILINE)
    html_text = re.sub(r'^```\s*\n', '', html_text, flags=re.MULTILINE)
    html_text = re.sub(r'\n```\s*$', '', html_text, flags=re.MULTILINE)
    html_text = re.sub(r'```html', '', html_text)
    html_text = re.sub(r'```', '', html_text)
    return html_text.strip()


def generate_website(category, domain=None, extra_context=None):
    """Full pipeline: plan → HTML → clean. Returns (plan, html)."""
    plan = generate_website_plan(category, domain=domain, extra_context=extra_context)
    html_raw = generate_html(plan, category, domain=domain, extra_context=extra_context)
    html = clean_html(html_raw)
    if not html:
        raise ValueError('HTML generation returned empty content')
    return plan, html


def _get_ssh_client():
    """Return a connected paramiko SSHClient using NPM SSH credentials."""
    import paramiko

    host = get_credential('npm', 'public_ip')
    if not host:
        raise ValueError('NPM Public IP not configured. Go to Settings → Nginx Proxy Manager.')

    username = get_credential('npm', 'ssh_username') or 'root'
    port = int(get_credential('npm', 'ssh_port') or 22)

    private_key_str = get_credential('npm', 'ssh_private_key')
    if not private_key_str:
        raise ValueError('NPM SSH private key not configured. Go to Settings → Nginx Proxy Manager → SSH Deploy.')

    key_file = io.StringIO(private_key_str)
    pkey = None
    for key_class in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
        try:
            key_file.seek(0)
            pkey = key_class.from_private_key(key_file)
            break
        except (paramiko.ssh_exception.SSHException, ValueError):
            continue
    if pkey is None:
        raise ValueError('Unsupported SSH private key format. Supported: RSA, Ed25519, ECDSA.')

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username,
        pkey=pkey,
        timeout=20,
        look_for_keys=False,
        allow_agent=False,
    )
    return client


def deploy_website(html, category):
    """
    Upload the generated HTML to the NPM host via SSH/SFTP.

    Creates  <deploy_path>/<slug>-<random>/index.html  on the remote host.
    Returns  {'folder': folder_name, 'path': remote_path}
    """
    deploy_path = (get_credential('npm', 'deploy_path') or '/var/www/html').rstrip('/')

    # Build folder name: <slug>-<6-digit random>
    slug = re.sub(r'[^a-z0-9]+', '-', category.lower()).strip('-') or 'site'
    suffix = ''.join(random.choices(string.digits, k=6))
    folder_name = f'{slug}-{suffix}'
    remote_dir = f'{deploy_path}/{folder_name}'

    client = _get_ssh_client()
    try:
        # Create the directory
        stdin, stdout, stderr = client.exec_command(f'mkdir -p {shlex.quote(remote_dir)}')
        stdout.channel.recv_exit_status()

        # Upload index.html and update docker-compose.yaml via SFTP
        sftp = client.open_sftp()
        try:
            with sftp.open(f'{remote_dir}/index.html', 'w') as f:
                f.write(html)

            # Read existing docker-compose.yaml or start fresh
            compose_file = f'{deploy_path}/docker-compose.yaml'
            try:
                with sftp.open(compose_file, 'r') as f:
                    compose_data = yaml.safe_load(f.read()) or {}
            except IOError:
                compose_data = {}

            if 'services' not in compose_data:
                compose_data['services'] = {}
            if 'networks' not in compose_data:
                compose_data['networks'] = {}
            compose_data['networks']['npm_network'] = {'external': True}

            compose_data['services'][f'nginx_{folder_name}'] = {
                'image': 'nginx:latest',
                'container_name': folder_name,
                'volumes': [f'./{folder_name}:/usr/share/nginx/html:ro'],
                'networks': ['npm_network'],
            }

            with sftp.open(compose_file, 'w') as f:
                f.write(yaml.dump(compose_data, default_flow_style=False, sort_keys=False))
        finally:
            sftp.close()
    finally:
        client.close()

    return {'folder': folder_name, 'path': remote_dir}


def publish_website(html, category, zone_id, zone_name, subdomain):
    """
    Full publish pipeline:
    1. Deploy index.html + update docker-compose.yaml on NPM host
    2. Relaunch containers
    3. Create NPM proxy host for <subdomain>.<zone_name>
    4. Create Cloudflare A record pointing to NPM public IP

    Returns {'steps': [...], 'fqdn': str, 'folder': str}.
    Each step: {'step': str, 'status': 'ok'|'error', ...extra}
    """
    from app.services import npm_service, dns_service

    steps = []
    folder_name = None
    fqdn = f'{subdomain}.{zone_name}' if subdomain else zone_name

    # Step 1: Deploy files
    try:
        deploy_result = deploy_website(html, category)
        folder_name = deploy_result['folder']
        steps.append({'step': 'deploy', 'status': 'ok',
                      'folder': folder_name, 'path': deploy_result['path']})
    except Exception as e:
        steps.append({'step': 'deploy', 'status': 'error', 'error': str(e)})
        return {'steps': steps, 'fqdn': fqdn, 'folder': None}

    # Step 2: Start only the new container — leave existing containers untouched
    # so their IPs stay stable. NPM resolves the container by name via Docker DNS.
    service_name = f'nginx_{folder_name}'
    try:
        start_container(service_name)
        steps.append({'step': 'relaunch', 'status': 'ok'})
    except Exception as e:
        steps.append({'step': 'relaunch', 'status': 'error', 'error': str(e)})

    # Step 3: NPM proxy host — always use container name (Docker DNS resolves it
    # reliably even after restarts, unlike IPs which can change).
    forward_host = folder_name
    try:
        proxy = npm_service.create_proxy_host(
            domain_names=[fqdn],
            forward_host=forward_host,
            forward_port=80,
        )
        steps.append({'step': 'npm_proxy', 'status': 'ok', 'proxy_id': proxy.get('id'),
                      'forward_host': forward_host})
    except Exception as e:
        steps.append({'step': 'npm_proxy', 'status': 'error', 'error': str(e)})

    # Step 4: Cloudflare DNS A record — proxied through Cloudflare
    try:
        npm_public_ip = get_credential('npm', 'public_ip')
        if not npm_public_ip:
            raise ValueError('NPM Public IP not configured. Go to Settings → Nginx Proxy Manager.')
        record_name = subdomain if subdomain else zone_name
        dns_record = dns_service.create_dns_record(
            zone_id=zone_id,
            record_type='A',
            name=record_name,
            content=npm_public_ip,
            ttl=1,
            proxied=True,
        )
        steps.append({'step': 'cloudflare_dns', 'status': 'ok',
                      'record_id': dns_record.get('id')})
    except Exception as e:
        steps.append({'step': 'cloudflare_dns', 'status': 'error', 'error': str(e)})

    return {'steps': steps, 'fqdn': fqdn, 'folder': folder_name}


def _get_container_ip(container_name):
    """
    Return the first Docker network IP of a running container, inspected via SSH.
    Mirrors the container IP extraction used by the Point Domain workflow.
    """
    client = _get_ssh_client()
    try:
        cmd = ('docker inspect ' + shlex.quote(container_name) +
               " --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'")
        stdin, stdout, stderr = client.exec_command(cmd)
        stdout.channel.recv_exit_status()
        ip = stdout.read().decode('utf-8', errors='replace').strip()
        return ip if ip else None
    finally:
        client.close()


def start_container(service_name):
    """
    SSH into the NPM host and run `docker compose up -d <service>` to start
    only the newly added service without touching existing containers.
    Returns {'stdout': str, 'stderr': str}.
    """
    deploy_path = (get_credential('npm', 'deploy_path') or '/var/www/html').rstrip('/')
    client = _get_ssh_client()
    try:
        cmd = (f'cd {shlex.quote(deploy_path)} && '
               f'docker compose up -d {shlex.quote(service_name)}')
        stdin, stdout, stderr = client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
    finally:
        client.close()

    if exit_code != 0:
        raise RuntimeError(err or out or f'Command exited with code {exit_code}')

    return {'stdout': out, 'stderr': err}


def relaunch_containers():
    """
    SSH into the NPM host and run `docker compose up -d` (no down) so that
    existing containers keep their IPs and only missing/updated services start.
    Returns {'stdout': str, 'stderr': str}.
    """
    deploy_path = (get_credential('npm', 'deploy_path') or '/var/www/html').rstrip('/')
    client = _get_ssh_client()
    try:
        cmd = f'cd {shlex.quote(deploy_path)} && docker compose up -d'
        stdin, stdout, stderr = client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
    finally:
        client.close()

    if exit_code != 0:
        raise RuntimeError(err or out or f'Command exited with code {exit_code}')

    return {'stdout': out, 'stderr': err}


def get_deployed_sites():
    """
    Discover all website-generator-deployed sites by:
    1. SSH to NPM host → read docker-compose.yaml → extract nginx_* container names
    2. Inspect each container to get its current IP
    3. Fetch NPM proxy hosts and match by forward_host == container_name or container_ip
    Returns a list of dicts: {fqdn, category, folder, npm_host_id, forward_host}
    """
    from app.services import npm_service

    deploy_path = (get_credential('npm', 'deploy_path') or '/var/www/html').rstrip('/')

    # Step 1: read docker-compose.yaml via SSH
    client = _get_ssh_client()
    try:
        sftp = client.open_sftp()
        try:
            with sftp.open(f'{deploy_path}/docker-compose.yaml', 'r') as f:
                compose_data = yaml.safe_load(f.read()) or {}
        except IOError:
            return []
        finally:
            sftp.close()
    finally:
        client.close()

    services = compose_data.get('services', {})

    # Step 2: extract containers from nginx_* services
    containers = {}  # container_name -> folder_name (same value, kept for clarity)
    for svc_name, svc_cfg in services.items():
        if not svc_name.startswith('nginx_'):
            continue
        if not isinstance(svc_cfg, dict):
            continue
        folder = svc_cfg.get('container_name', svc_name[len('nginx_'):])
        containers[folder] = folder

    if not containers:
        return []

    # Step 3: get current IPs for running containers (best-effort)
    container_ips = {}  # container_name -> ip
    for folder in containers:
        try:
            ip = _get_container_ip(folder)
            if ip:
                container_ips[folder] = ip
        except Exception:
            pass

    # Build a reverse lookup: ip/name -> folder
    lookup = {}
    for folder in containers:
        lookup[folder] = folder
        if folder in container_ips:
            lookup[container_ips[folder]] = folder

    # Step 4: fetch NPM proxy hosts and match
    npm_hosts = npm_service.list_proxy_hosts()

    results = []
    for host in npm_hosts:
        fwd = host.get('forward_host', '')
        domain_names = host.get('domain_names') or []
        if not domain_names or not fwd:
            continue
        folder = lookup.get(fwd)
        if not folder:
            continue
        fqdn = domain_names[0]
        # Recover readable category from slug (e.g. "law-firm-123456" → "Law Firm")
        category_slug = re.sub(r'-\d{6}$', '', folder)
        category = category_slug.replace('-', ' ').title()
        results.append({
            'fqdn': fqdn,
            'category': category,
            'folder': folder,
            'npm_host_id': host.get('id'),
            'forward_host': fwd,
        })

    return results


def remove_deployed_site(folder_name):
    """
    Remove a website-generator site from the NPM host:
    1. Stop and remove the Docker container
    2. Remove the nginx_{folder_name} service from docker-compose.yaml
    Returns {'stopped': bool, 'compose_updated': bool}
    """
    deploy_path = (get_credential('npm', 'deploy_path') or '/var/www/html').rstrip('/')
    result = {'stopped': False, 'compose_updated': False}

    client = _get_ssh_client()
    try:
        # Stop and remove the container
        cmd = f'docker stop {shlex.quote(folder_name)} && docker rm {shlex.quote(folder_name)}'
        stdin, stdout, stderr = client.exec_command(cmd)
        stdout.channel.recv_exit_status()
        result['stopped'] = True

        # Update docker-compose.yaml
        sftp = client.open_sftp()
        try:
            compose_file = f'{deploy_path}/docker-compose.yaml'
            try:
                with sftp.open(compose_file, 'r') as f:
                    compose_data = yaml.safe_load(f.read()) or {}
            except IOError:
                compose_data = {}

            svc_key = f'nginx_{folder_name}'
            if 'services' in compose_data and svc_key in compose_data['services']:
                del compose_data['services'][svc_key]
                with sftp.open(compose_file, 'w') as f:
                    f.write(yaml.dump(compose_data, default_flow_style=False, sort_keys=False))
                result['compose_updated'] = True
        finally:
            sftp.close()
    finally:
        client.close()

    return result

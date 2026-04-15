"""AI-powered phishing email template generation using Azure OpenAI."""

import json
import logging
import re
from datetime import datetime

from app import db
from app.models.ia_email_template import IAEmailTemplateBatch, IAEmailTemplate
from app.models.ia_business_intel import IABusinessIntel
from app.models.project import Project
from app.services import discovery_service
from app.services.openai_service import get_client

_log = logging.getLogger(__name__)

_MAX_CONTEXT_ITEMS = 20  # cap list items sent in the prompt
_MAX_ASSETS_IN_PROMPT = 200  # cap total assets fed to the prompt builder


def _build_prompt(project, intel, assets, extras, sources):
    """Assemble the system prompt from aggregated recon data.

    Parameters
    ----------
    project : Project
    intel : IABusinessIntel | None
    assets : list[dict]
        Unified asset list from discovery_service (each has ``sources`` list).
    extras : dict
        Non-asset findings (``emails``, ``breaches``).
    sources : list[str]
        Source tags that contributed data (e.g. ``['fofa', 'scanner']``).
    """
    company = project.company
    company_name = company.name if company else 'Unknown'
    company_industry = company.industry if company else 'Unknown'
    company_desc = (company.description or '') if company else ''

    # ── Intel section ───────────────────────────────────────────────
    intel_parts = []
    field_labels = {
        'company_overview': 'Company Overview',
        'key_products': 'Key Products/Services',
        'recent_news': 'Recent News & Events',
        'tech_stack': 'Technology Stack',
        'key_departments': 'Key Departments & Roles',
        'vendor_partners': 'Vendor/Partner Relationships',
        'social_presence': 'Social Media Presence & Tone',
        'raw_osint': 'Additional OSINT',
        'notes': 'Operator Notes',
    }
    if intel:
        for field, label in field_labels.items():
            val = getattr(intel, field, None)
            if val and val.strip():
                intel_parts.append(f"{label}:\n{val.strip()}")

    intel_block = '\n\n'.join(intel_parts) if intel_parts else 'No business intelligence available.'

    # ── Recon findings (aggregated from all sources) ────────────────
    recon_block = 'No recon data available.'

    capped = assets[:_MAX_ASSETS_IN_PROMPT]
    if capped or extras.get('emails') or extras.get('breaches'):
        parts = []

        # Source attribution
        if sources:
            parts.append(f"Data sources: {', '.join(sources)}")

        # Hostnames / subdomains
        all_hosts = set()
        for a in capped:
            all_hosts.update(a.get('hostnames', []))
        if all_hosts:
            shown = sorted(all_hosts)[:_MAX_CONTEXT_ITEMS]
            parts.append(f"Subdomains/Hosts ({len(all_hosts)} total): {', '.join(shown)}")

        # Domains
        all_domains = {a.get('domain') for a in capped if a.get('domain')}
        if all_domains:
            shown = sorted(all_domains)[:_MAX_CONTEXT_ITEMS]
            parts.append(f"Domains ({len(all_domains)} total): {', '.join(shown)}")

        # Technologies (from asset tags + server headers)
        techs = {}
        for a in capped:
            for t in a.get('technologies', []):
                techs[t] = techs.get(t, 0) + 1
            srv = a.get('server', '')
            if srv:
                techs[srv] = techs.get(srv, 0) + 1
        if techs:
            top = sorted(techs.items(), key=lambda x: -x[1])[:_MAX_CONTEXT_ITEMS]
            parts.append(f"Technologies/Servers: {', '.join(f'{t} ({c})' for t, c in top)}")

        # Open ports / services
        port_svc = {}
        for a in capped:
            p = a.get('port', '')
            if p and p != '0':
                svc = a.get('service') or a.get('protocol') or ''
                label = f"{p}/{svc}" if svc else str(p)
                port_svc[label] = port_svc.get(label, 0) + 1
        if port_svc:
            top = sorted(port_svc.items(), key=lambda x: -x[1])[:_MAX_CONTEXT_ITEMS]
            parts.append(f"Open ports/services: {', '.join(f'{ps} ({c})' for ps, c in top)}")

        # Page titles (from FOFA / future sources)
        titles = {}
        for a in capped:
            t = a.get('title', '')
            if t:
                titles[t] = titles.get(t, 0) + 1
        if titles:
            top = sorted(titles.items(), key=lambda x: -x[1])[:_MAX_CONTEXT_ITEMS]
            parts.append(f"Page titles: {', '.join(f'{t} ({c})' for t, c in top)}")

        # Emails (extras — from scanner or future sources)
        emails = extras.get('emails', [])
        if emails:
            shown = emails[:10]
            parts.append(f"Discovered emails ({len(emails)} total): {', '.join(str(e) for e in shown)}")

        # Breaches (extras — from scanner or future sources)
        breaches = extras.get('breaches', [])
        if breaches:
            parts.append(f"Breach records found: {len(breaches)}")

        # Total asset count
        parts.append(f"Total exposed assets: {len(assets)}")

        if parts:
            recon_block = '\n'.join(parts)

    prompt = f"""You are a red team social engineering specialist generating phishing email templates for an authorized security awareness engagement.

TARGET COMPANY:
Name: {company_name}
Industry: {company_industry}
Description: {company_desc}

BUSINESS INTELLIGENCE:
{intel_block}

AGGREGATED RECON FINDINGS (from {', '.join(sources) if sources else 'no sources'}):
{recon_block}

INSTRUCTIONS:
Generate between 3 and 6 phishing email templates. For each template:
- Identify a realistic pretext that a {company_name} employee would find credible
- Use discovered technologies to craft technical lures where appropriate
- Use email patterns from discovered addresses for sender spoofing suggestions
- Leverage recent news, vendor relationships, or industry events as pretexts when available
- Recommend which employee roles or departments are most susceptible to each template
- Vary the psychological levers: urgency, authority, curiosity, fear, social proof, reciprocity
- Write both the full HTML body (professional email formatting) and a plain-text version
- Include {{{{.FirstName}}}} and {{{{.LastName}}}} GoPhish placeholders in the body where appropriate
- Include a {{{{.URL}}}} GoPhish placeholder for the phishing link

Return ONLY a JSON array with this exact schema (no markdown, no preamble):
[{{
  "pretext_category": "string - e.g. IT Helpdesk, HR Payroll, Vendor Invoice, CEO Request",
  "subject": "string - email subject line",
  "html_body": "string - full HTML email body",
  "text_body": "string - plain text version",
  "target_roles": ["string array - roles most susceptible, e.g. Finance, IT Admin, C-suite, HR"],
  "sender_suggestion": "string - e.g. IT Support <it-support@example.com>",
  "relevance_score": "integer 1-10 based on how well the pretext fits the available intelligence",
  "notes": "string - brief rationale for why this pretext is effective"
}}]"""

    return prompt


def run_generation(batch_id, project_id):
    """Execute the email template generation pipeline. Updates the batch record in-place."""
    batch = IAEmailTemplateBatch.query.get(batch_id)
    if not batch:
        raise ValueError(f'Batch {batch_id} not found')

    try:
        project = Project.query.get(project_id)
        if not project:
            raise ValueError(f'Project {project_id} not found')

        # Load business intel
        intel = IABusinessIntel.query.filter_by(project_id=project_id).first()

        # Aggregate all recon data
        data = discovery_service.aggregate_assets(project_id)
        assets = data['assets']
        extras = data['extras']
        sources = data['sources']

        # Record which sources fed this batch
        batch.data_sources = json.dumps(sources)

        # Build prompt and call LLM
        prompt = _build_prompt(project, intel, assets, extras, sources)
        client, deployment = get_client()
        from app.services.openai_service import completion_kwargs

        response = client.chat.completions.create(
            model=deployment,
            messages=[{'role': 'user', 'content': prompt}],
            **completion_kwargs(max_tokens=8000, temperature=0.7),
        )
        content = response.choices[0].message.content

        # Parse JSON array from response (strip markdown fences if present)
        content = re.sub(r'^```(?:json)?\s*', '', content.strip())
        content = re.sub(r'\s*```$', '', content.strip())
        templates_data = json.loads(content)

        if not isinstance(templates_data, list):
            raise ValueError('LLM response is not a JSON array')

        # Create template records
        for i, t in enumerate(templates_data):
            tpl = IAEmailTemplate(
                batch_id=batch.id,
                project_id=project_id,
                name=t.get('pretext_category', f'Template {i + 1}'),
                subject=t.get('subject', '(no subject)'),
                html_body=t.get('html_body', ''),
                text_body=t.get('text_body', ''),
                pretext_category=t.get('pretext_category', ''),
                target_roles=json.dumps(t.get('target_roles', [])),
                sender_suggestion=t.get('sender_suggestion', ''),
                relevance_score=min(max(int(t.get('relevance_score', 5)), 1), 10),
                notes=t.get('notes', ''),
            )
            db.session.add(tpl)

        batch.status = 'completed'
        db.session.commit()

    except Exception as e:
        _log.exception('Email template generation failed for batch %s', batch_id)
        db.session.rollback()
        batch = IAEmailTemplateBatch.query.get(batch_id)
        if batch:
            batch.status = 'failed'
            batch.error_message = str(e)[:2000]
            db.session.commit()
        raise


def push_template_to_gophish(template_id, user_id=None):
    """Push a generated template and its assigned targets as a group to GoPhish.

    Also creates a draft IACampaign pre-loaded with the template and targets.
    """
    from app.services import gophish_service, ia_campaign_service

    tpl = IAEmailTemplate.query.get(template_id)
    if not tpl:
        raise ValueError('Template not found')

    gp_data = {
        'name': f'[Citadel] {tpl.name} - {tpl.subject[:50]}',
        'subject': tpl.subject,
        'html': tpl.html_body or '',
        'text': tpl.text_body or '',
    }
    result = gophish_service.create_template(gp_data)
    tpl.gophish_template_id = result.get('id')

    group_result = None
    assigned = tpl.assigned_targets.all()
    if assigned:
        gp_targets = []
        for t in assigned:
            if not t.email:
                continue
            gp_targets.append({
                'first_name': t.first_name or '',
                'last_name': t.last_name or '',
                'email': t.email,
                'position': t.job_title or '',
            })

        if gp_targets:
            ts = int(datetime.utcnow().timestamp())
            group_name = f'[Citadel] {tpl.name or tpl.subject[:40]} ({len(gp_targets)}) - {ts}'
            group_result = gophish_service.create_group({
                'name': group_name,
                'targets': gp_targets,
            })
            tpl.gophish_group_id = group_result.get('id')

    tpl.pushed_at = datetime.utcnow()
    db.session.commit()

    # Create a draft campaign pre-loaded with template + targets
    campaign_dict = None
    if user_id:
        campaign_name = f'{tpl.name or tpl.subject[:60]}'
        campaign = ia_campaign_service.create_campaign(
            tpl.project_id,
            {'name': campaign_name, 'vector': 'phishing', 'email_template_id': tpl.id},
            user_id,
        )
        target_ids = [t.id for t in assigned]
        if target_ids:
            ia_campaign_service.add_targets(campaign, target_ids)
        campaign_dict = campaign.to_dict()

    return {'template': result, 'group': group_result, 'campaign': campaign_dict}

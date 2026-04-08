"""AI-powered phishing email template generation using Azure OpenAI."""

import json
import logging
import re
from datetime import datetime

from app import db
from app.models.ia_email_template import IAEmailTemplateBatch, IAEmailTemplate
from app.models.ia_business_intel import IABusinessIntel
from app.models.ia_scan_job import IAScanJob
from app.models.project import Project
from app.services.openai_service import get_client

_log = logging.getLogger(__name__)

_MAX_CONTEXT_ITEMS = 20  # cap list items sent in the prompt


def _build_prompt(project, intel, scan_results):
    """Assemble the system prompt with all available context."""
    company = project.company
    company_name = company.name if company else 'Unknown'
    company_industry = company.industry if company else 'Unknown'
    company_desc = (company.description or '') if company else ''

    # Build intel section (only non-empty fields)
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

    # Build scan findings section
    scan_block = 'No scan data available.'
    if scan_results:
        parts = []
        subs = scan_results.get('subdomains', [])
        if subs:
            shown = subs[:_MAX_CONTEXT_ITEMS]
            parts.append(f"Subdomains ({len(subs)} total): {', '.join(str(s) for s in shown)}")

        techs = scan_results.get('technologies', [])
        if techs:
            shown = techs[:_MAX_CONTEXT_ITEMS]
            tech_strs = []
            for t in shown:
                if isinstance(t, dict):
                    tech_strs.append(t.get('name', str(t)))
                else:
                    tech_strs.append(str(t))
            parts.append(f"Technologies: {', '.join(tech_strs)}")

        emails = scan_results.get('emails', [])
        if emails:
            shown = emails[:10]
            parts.append(f"Discovered emails ({len(emails)} total): {', '.join(str(e) for e in shown)}")

        ports = scan_results.get('open_ports', [])
        if ports:
            shown = ports[:_MAX_CONTEXT_ITEMS]
            port_strs = []
            for p in shown:
                if isinstance(p, dict):
                    port_strs.append(f"{p.get('port', '?')}/{p.get('service', '?')}")
                else:
                    port_strs.append(str(p))
            parts.append(f"Open ports/services: {', '.join(port_strs)}")

        breaches = scan_results.get('breaches', [])
        if breaches:
            parts.append(f"Breach records found: {len(breaches)}")

        if parts:
            scan_block = '\n'.join(parts)

    prompt = f"""You are a red team social engineering specialist generating phishing email templates for an authorized security awareness engagement.

TARGET COMPANY:
Name: {company_name}
Industry: {company_industry}
Description: {company_desc}

BUSINESS INTELLIGENCE:
{intel_block}

RECON FINDINGS (from automated external surface scan):
{scan_block}

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


def run_generation(batch_id, project_id, scan_job_id=None):
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

        # Load scan results
        scan_results = None
        if scan_job_id:
            job = IAScanJob.query.get(scan_job_id)
            if job and job.raw_results:
                scan_results = json.loads(job.raw_results)
        else:
            # Use most recent completed scan for this project
            job = (IAScanJob.query
                   .filter_by(project_id=project_id, status='completed')
                   .order_by(IAScanJob.completed_at.desc())
                   .first())
            if job and job.raw_results:
                scan_results = json.loads(job.raw_results)
                batch.scan_job_id = job.id

        # Build prompt and call LLM
        prompt = _build_prompt(project, intel, scan_results)
        client, deployment = get_client()

        response = client.chat.completions.create(
            model=deployment,
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=8000,
            temperature=0.7,
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


def push_template_to_gophish(template_id):
    """Push a generated template to GoPhish and record the GoPhish template ID."""
    from app.services import gophish_service

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
    tpl.pushed_at = datetime.utcnow()
    db.session.commit()

    return result

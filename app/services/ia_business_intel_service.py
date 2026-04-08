import json
import logging
import re
from datetime import datetime

from app import db
from app.models.ia_business_intel import IABusinessIntel, INTEL_FIELDS

_log = logging.getLogger(__name__)

_EXTRACTION_FIELDS = [
    'company_overview', 'key_products', 'recent_news', 'tech_stack',
    'key_departments', 'vendor_partners', 'social_presence', 'raw_osint', 'notes',
]


def get_or_create_intel(project_id):
    """Return the IABusinessIntel row for a project, creating an empty one if needed."""
    intel = IABusinessIntel.query.filter_by(project_id=project_id).first()
    if not intel:
        intel = IABusinessIntel(project_id=project_id)
        db.session.add(intel)
        db.session.commit()
    return intel


def update_intel(project_id, fields, updated_by_id):
    """Update whitelisted fields on the business intel record."""
    intel = get_or_create_intel(project_id)
    for key, value in fields.items():
        if key in INTEL_FIELDS:
            setattr(intel, key, value)
    intel.updated_by_id = updated_by_id
    intel.updated_at = datetime.utcnow()
    db.session.commit()
    return intel


def extract_fields_from_text(raw_text):
    """Use Azure OpenAI to extract structured intel fields from pasted markdown."""
    from app.services.openai_service import get_client

    prompt = """You are a threat intelligence data extraction assistant. Given a markdown threat intelligence report, extract structured information into exactly these JSON fields.

The report typically contains sections like:
- "Business Intelligence > Overview" — company background, products, departments
- "Competitive Analysis" — market position, competitors, recent developments
- "Competitor Comparison" — comparative data
- "SWOT Analysis" — strengths, weaknesses, opportunities, threats

Map the content to these fields:
- company_overview: Company background, mission, size, locations, industry position
- key_products: Main products, services, SaaS offerings
- recent_news: Recent events, mergers, acquisitions, launches, market moves, competitive analysis insights
- tech_stack: Known technologies, cloud providers, software platforms
- key_departments: Organizational structure, key departments, notable roles
- vendor_partners: Known vendors, partners, suppliers, contractors, competitors
- social_presence: Social media activity, brand tone, public communications style
- raw_osint: Any data that doesn't fit the above categories (SWOT details, misc intelligence)
- notes: Leave empty (reserved for operator)

Return ONLY a JSON object with these 9 keys. Every value must be a string (use newlines within strings for lists). If no data is available for a field, use an empty string."""

    client, deployment = get_client()

    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {'role': 'system', 'content': prompt},
            {'role': 'user', 'content': raw_text[:15000]},  # cap to stay within context
        ],
        max_tokens=4000,
        temperature=0.2,
    )

    content = response.choices[0].message.content
    content = re.sub(r'^```(?:json)?\s*', '', content.strip())
    content = re.sub(r'\s*```$', '', content.strip())

    try:
        fields = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f'Failed to parse LLM response as JSON: {e}')

    if not isinstance(fields, dict):
        raise ValueError('LLM response is not a JSON object')

    # Ensure all expected keys exist
    result = {}
    for key in _EXTRACTION_FIELDS:
        result[key] = str(fields.get(key, ''))

    return result

import logging
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app import db
from app.models.license import License
from app.models.user import User
from app.models.domain import Domain
from app.services.plan_service import get_current_plan, invalidate_plan_cache, TIERS, TIER_ORDER
from app.utils.decorators import admin_required

_log = logging.getLogger(__name__)

# Human-readable labels for each feature key
_FEATURE_LABELS = {
    'gophish':           'GoPhish Sending Profiles',
    'cobaltstrike':      'Cobalt Strike Listeners',
    'website_generator': 'AI Website Generator',
    'infra_map':         'Infrastructure Map',
    'api_access':        'API Token Access',
    'engagements':       'Engagement Management',
}


@api_bp.route('/license', methods=['GET'])
@login_required
def get_license():
    """Return current plan info and usage stats. Available to all authenticated users."""
    plan = get_current_plan()
    current_users = User.query.count()
    current_domains = Domain.query.count()

    return jsonify({
        'tier': plan.tier,
        'display_name': plan.display_name,
        'org_name': plan.org_name,
        'features': sorted(plan.features),
        'feature_labels': _FEATURE_LABELS,
        'max_users': plan.max_users,
        'max_domains': plan.max_domains,
        'current_users': current_users,
        'current_domains': current_domains,
        'tiers': {
            key: {
                'display_name': cfg['display_name'],
                'description': cfg['description'],
                'max_users': cfg['max_users'],
                'max_domains': cfg['max_domains'],
                'features': sorted(cfg['features']),
            }
            for key, cfg in TIERS.items()
        },
        'tier_order': list(TIER_ORDER),
    })


@api_bp.route('/license', methods=['PATCH'])
@login_required
@admin_required
def update_license():
    """Update the active plan tier and/or org name. Admin only."""
    data = request.get_json(silent=True) or {}

    tier = data.get('tier')
    org_name = data.get('org_name')

    if tier is not None and tier not in TIERS:
        return jsonify({'error': f'Invalid tier. Must be one of: {", ".join(TIER_ORDER)}'}), 400

    lic = License.query.first()
    if lic is None:
        lic = License()
        db.session.add(lic)

    if tier is not None:
        lic.tier = tier
    if org_name is not None:
        lic.org_name = org_name.strip()

    lic.updated_by_id = current_user.id
    db.session.commit()

    # Invalidate the per-request cache so next read reflects the new plan
    invalidate_plan_cache()

    _log.info('Admin %s changed license tier to %s', current_user.email, lic.tier)

    # Return fresh plan info
    plan = get_current_plan()
    return jsonify({
        'saved': True,
        'tier': plan.tier,
        'display_name': plan.display_name,
        'org_name': plan.org_name,
    })

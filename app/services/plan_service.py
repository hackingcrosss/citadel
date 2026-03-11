"""plan_service.py — Subscription tier definitions and plan enforcement helpers.

Usage:
    from app.services.plan_service import get_current_plan, TIERS

    plan = get_current_plan()
    plan.is_enabled('cobaltstrike')   # → True/False
    plan.at_user_limit(User.query.count())  # → True/False
"""

import logging
from flask import g

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier definitions — single source of truth for features and limits
# ---------------------------------------------------------------------------

#: All features that can be gated by plan
ALL_FEATURES = frozenset({
    'gophish',
    'cobaltstrike',
    'website_generator',
    'infra_map',
    'projects',
    'cdn',
    'api_access',
    'engagements',        # Phase 2
})

TIERS = {
    'community': {
        'display_name': 'Community',
        'description': 'Core infrastructure management for individuals.',
        'max_users': 1,
        'max_domains': 3,
        'features': frozenset(),
    },
    'professional': {
        'display_name': 'Professional',
        'description': 'Full phishing toolkit for small red teams.',
        'max_users': 5,
        'max_domains': 20,
        'features': frozenset({'gophish', 'website_generator'}),
    },
    'team': {
        'display_name': 'Team',
        'description': 'Complete red team platform with C2 and mapping.',
        'max_users': 20,
        'max_domains': -1,   # -1 = unlimited
        'features': frozenset({'gophish', 'website_generator', 'cobaltstrike', 'infra_map', 'projects', 'cdn'}),
    },
    'enterprise': {
        'display_name': 'Enterprise',
        'description': 'Unlimited scale with all current and future features.',
        'max_users': -1,
        'max_domains': -1,
        'features': frozenset(ALL_FEATURES),
    },
}

TIER_ORDER = ('community', 'professional', 'team', 'enterprise')


# ---------------------------------------------------------------------------
# PlanInfo — the resolved plan for the current request
# ---------------------------------------------------------------------------

class PlanInfo:
    """Resolved plan metadata for the active license.

    Do not instantiate directly — use get_current_plan().
    """

    def __init__(self, tier: str, max_users: int, max_domains: int,
                 features: frozenset, org_name: str):
        self.tier = tier
        self.display_name = TIERS.get(tier, TIERS['community'])['display_name']
        self.description = TIERS.get(tier, TIERS['community'])['description']
        self.max_users = max_users      # -1 = unlimited
        self.max_domains = max_domains  # -1 = unlimited
        self.features = features        # frozenset of enabled feature strings
        self.org_name = org_name

    # ------------------------------------------------------------------
    # Feature checks
    # ------------------------------------------------------------------

    def is_enabled(self, feature: str) -> bool:
        """Return True if the given feature is available on this plan."""
        return feature in self.features

    # ------------------------------------------------------------------
    # Limit checks
    # ------------------------------------------------------------------

    def at_user_limit(self, current_count: int) -> bool:
        """Return True if current_count has reached or exceeded the user limit."""
        if self.max_users == -1:
            return False
        return current_count >= self.max_users

    def at_domain_limit(self, current_count: int) -> bool:
        """Return True if current_count has reached or exceeded the domain limit."""
        if self.max_domains == -1:
            return False
        return current_count >= self.max_domains

    def users_remaining(self) -> int:
        """Return remaining user slots, or -1 for unlimited."""
        if self.max_users == -1:
            return -1
        from app.models.user import User
        used = User.query.count()
        return max(0, self.max_users - used)

    def domains_remaining(self) -> int:
        """Return remaining domain slots, or -1 for unlimited."""
        if self.max_domains == -1:
            return -1
        from app.models.domain import Domain
        used = Domain.query.count()
        return max(0, self.max_domains - used)


# ---------------------------------------------------------------------------
# get_current_plan — main entry point
# ---------------------------------------------------------------------------

def get_current_plan() -> PlanInfo:
    """Load and return the active PlanInfo for this request.

    Cached on Flask's g object so the DB is queried at most once per request.
    Falls back to a Community plan if no license row exists.

    Admin users always receive an unlimited Enterprise plan, bypassing all
    license restrictions.
    """
    if hasattr(g, '_current_plan'):
        return g._current_plan

    # Admin users bypass the license system entirely — they always get
    # an unlimited Enterprise plan with every feature enabled.
    # Non-admin users may have a per-user plan_override that takes precedence
    # over the global license.
    try:
        from flask_login import current_user
        if current_user.is_authenticated:
            if current_user.is_admin:
                plan = PlanInfo(
                    tier='enterprise',
                    max_users=-1,
                    max_domains=-1,
                    features=ALL_FEATURES,
                    org_name='',
                )
                g._current_plan = plan
                return plan

            override = getattr(current_user, 'plan_override', None)
            if override and override in TIERS:
                tier_cfg = TIERS[override]
                plan = PlanInfo(
                    tier=override,
                    max_users=tier_cfg['max_users'],
                    max_domains=tier_cfg['max_domains'],
                    features=tier_cfg['features'],
                    org_name='',
                )
                g._current_plan = plan
                return plan
    except Exception:
        pass

    try:
        from app.models.license import License
        lic = License.query.first()
    except Exception:
        # DB not yet initialised (e.g. during init_db.py run)
        lic = None

    if lic is None:
        plan = PlanInfo(
            tier='community',
            max_users=1,
            max_domains=3,
            features=TIERS['community']['features'],
            org_name='',
        )
        g._current_plan = plan
        return plan

    tier_key = lic.tier if lic.tier in TIERS else 'community'
    tier_cfg = TIERS[tier_key]

    max_users = lic.custom_max_users if lic.custom_max_users is not None else tier_cfg['max_users']
    max_domains = lic.custom_max_domains if lic.custom_max_domains is not None else tier_cfg['max_domains']

    plan = PlanInfo(
        tier=tier_key,
        max_users=max_users,
        max_domains=max_domains,
        features=tier_cfg['features'],
        org_name=lic.org_name or '',
    )
    g._current_plan = plan
    return plan


def invalidate_plan_cache():
    """Clear the per-request plan cache after a license update."""
    if hasattr(g, '_current_plan'):
        del g._current_plan

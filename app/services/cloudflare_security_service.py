"""Cloudflare security rule management — IP access rules, WAF custom rules, security level."""

import logging
from app.services.dns_service import _request

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Security Level
# ---------------------------------------------------------------------------

def get_security_level(zone_id, label='default'):
    data = _request('GET', f'/zones/{zone_id}/settings/security_level', label=label)
    return data['result']


def set_security_level(zone_id, value, label='default'):
    valid = ('off', 'essentially_off', 'low', 'medium', 'high', 'under_attack')
    if value not in valid:
        raise ValueError(f"Invalid security level: {value}. Must be one of {valid}")
    data = _request('PATCH', f'/zones/{zone_id}/settings/security_level',
                    label=label, json={'value': value})
    return data['result']


# ---------------------------------------------------------------------------
# IP Access Rules
# ---------------------------------------------------------------------------

def list_ip_access_rules(zone_id, label='default', page=1, per_page=50):
    data = _request('GET', f'/zones/{zone_id}/firewall/access_rules/rules',
                    label=label, params={'page': page, 'per_page': per_page})
    rules = []
    for r in data.get('result', []):
        rules.append({
            'id': r['id'],
            'mode': r.get('mode', ''),
            'target': r.get('configuration', {}).get('target', ''),
            'value': r.get('configuration', {}).get('value', ''),
            'notes': r.get('notes', ''),
            'created_on': r.get('created_on', ''),
            'modified_on': r.get('modified_on', ''),
        })
    return rules


def create_ip_access_rule(zone_id, mode, target, value, notes='', label='default'):
    valid_modes = ('block', 'challenge', 'whitelist', 'js_challenge', 'managed_challenge')
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode: {mode}. Must be one of {valid_modes}")
    valid_targets = ('ip', 'ip_range', 'country', 'asn')
    if target not in valid_targets:
        raise ValueError(f"Invalid target: {target}. Must be one of {valid_targets}")
    payload = {
        'mode': mode,
        'configuration': {'target': target, 'value': value},
        'notes': notes,
    }
    data = _request('POST', f'/zones/{zone_id}/firewall/access_rules/rules',
                    label=label, json=payload)
    r = data['result']
    return {
        'id': r['id'],
        'mode': r.get('mode', ''),
        'target': r.get('configuration', {}).get('target', ''),
        'value': r.get('configuration', {}).get('value', ''),
        'notes': r.get('notes', ''),
    }


def update_ip_access_rule(zone_id, rule_id, mode, notes=None, label='default'):
    valid_modes = ('block', 'challenge', 'whitelist', 'js_challenge', 'managed_challenge')
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode: {mode}. Must be one of {valid_modes}")
    payload = {'mode': mode}
    if notes is not None:
        payload['notes'] = notes
    data = _request('PATCH', f'/zones/{zone_id}/firewall/access_rules/rules/{rule_id}',
                    label=label, json=payload)
    r = data['result']
    return {
        'id': r['id'],
        'mode': r.get('mode', ''),
        'target': r.get('configuration', {}).get('target', ''),
        'value': r.get('configuration', {}).get('value', ''),
        'notes': r.get('notes', ''),
    }


def delete_ip_access_rule(zone_id, rule_id, label='default'):
    _request('DELETE', f'/zones/{zone_id}/firewall/access_rules/rules/{rule_id}',
             label=label)
    return True


# ---------------------------------------------------------------------------
# WAF Custom Rules (Rulesets API)
# ---------------------------------------------------------------------------

def list_custom_rules(zone_id, label='default'):
    try:
        data = _request('GET',
                        f'/zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint',
                        label=label)
    except Exception as e:
        if 'could not find' in str(e).lower() or 'not_found' in str(e).lower():
            return []
        raise
    rules = []
    for r in data.get('result', {}).get('rules', []):
        rules.append({
            'id': r['id'],
            'action': r.get('action', ''),
            'expression': r.get('expression', ''),
            'description': r.get('description', ''),
            'enabled': r.get('enabled', True),
            'ref': r.get('ref', ''),
            'last_updated': r.get('last_updated', ''),
        })
    return rules


def _get_entrypoint_ruleset_id(zone_id, label='default'):
    data = _request('GET',
                    f'/zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint',
                    label=label)
    return data.get('result', {}).get('id')


def create_custom_rule(zone_id, action, expression, description='', enabled=True, label='default'):
    valid_actions = ('block', 'challenge', 'js_challenge', 'managed_challenge', 'skip', 'log')
    if action not in valid_actions:
        raise ValueError(f"Invalid action: {action}. Must be one of {valid_actions}")
    if not expression.strip():
        raise ValueError("Expression is required")
    payload = {
        'action': action,
        'expression': expression,
        'description': description,
        'enabled': enabled,
    }
    data = _request('POST',
                    f'/zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint/rules',
                    label=label, json=payload)
    rules = data.get('result', {}).get('rules', [])
    if rules:
        r = rules[-1]
        return {
            'id': r['id'],
            'action': r.get('action', ''),
            'expression': r.get('expression', ''),
            'description': r.get('description', ''),
            'enabled': r.get('enabled', True),
        }
    return {}


def update_custom_rule(zone_id, rule_id, action, expression, description='', enabled=True, label='default'):
    valid_actions = ('block', 'challenge', 'js_challenge', 'managed_challenge', 'skip', 'log')
    if action not in valid_actions:
        raise ValueError(f"Invalid action: {action}. Must be one of {valid_actions}")
    if not expression.strip():
        raise ValueError("Expression is required")
    ruleset_id = _get_entrypoint_ruleset_id(zone_id, label=label)
    if not ruleset_id:
        raise ValueError('No custom ruleset found for this zone')
    payload = {
        'action': action,
        'expression': expression,
        'description': description,
        'enabled': enabled,
    }
    data = _request('PATCH', f'/zones/{zone_id}/rulesets/{ruleset_id}/rules/{rule_id}',
                    label=label, json=payload)
    rules = data.get('result', {}).get('rules', [])
    for r in rules:
        if r.get('id') == rule_id:
            return {
                'id': r['id'],
                'action': r.get('action', ''),
                'expression': r.get('expression', ''),
                'description': r.get('description', ''),
                'enabled': r.get('enabled', True),
            }
    return {}


def delete_custom_rule(zone_id, rule_id, label='default'):
    ruleset_id = _get_entrypoint_ruleset_id(zone_id, label=label)
    if not ruleset_id:
        raise ValueError('No custom ruleset found for this zone')
    _request('DELETE',
             f'/zones/{zone_id}/rulesets/{ruleset_id}/rules/{rule_id}',
             label=label)
    return True

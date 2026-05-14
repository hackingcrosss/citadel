from functools import wraps
from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import hetzner_service
from app import db
from app.models.instance_tag import InstanceTag
from app.models.instance_ssh_config import InstanceSSHConfig
from app.services.credential_service import _get_fernet, get_account_labels
from app.utils.decorators import admin_required
from app.services import audit_service
from app.utils.errors import safe_error


_PROVIDER = 'hetzner'


def _hetzner_configured_required(f):
    """Return 404 when no Hetzner credentials are configured.

    Layered on top of @login_required. Prevents operators (and admins) from
    calling Hetzner endpoints when the integration is disabled, while still
    letting admins add credentials via the Settings page.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_account_labels(_PROVIDER):
            return jsonify({'error': 'Hetzner integration not configured'}), 404
        return f(*args, **kwargs)
    return decorated


def _server_label(server_id):
    """Resolve account label for a server ID.

    Lookup order:
    1. In-memory cache populated by list_servers_all_accounts().
    2. First configured Hetzner account label.
    """
    cached = hetzner_service._server_account_cache.get(str(server_id))
    if cached:
        return cached
    labels = get_account_labels(_PROVIDER)
    return labels[0] if labels else 'default'


# --- Servers ---

@api_bp.route('/hetzner/servers', methods=['GET'])
@login_required
@_hetzner_configured_required
def hetzner_list_servers():
    try:
        servers = hetzner_service.list_servers_all_accounts()
        server_ids = [s['id'] for s in servers]

        # Enrich with local tags (provider-scoped)
        if server_ids:
            tags = InstanceTag.query.filter(
                InstanceTag.provider == _PROVIDER,
                InstanceTag.instance_id.in_(server_ids),
            ).all()
            tag_map = {}
            for t in tags:
                tag_map.setdefault(t.instance_id, []).append(t.tag)
            for s in servers:
                s['local_tags'] = tag_map.get(s['id'], [])

            # Enrich with SSH config status
            ssh_configs = InstanceSSHConfig.query.filter(
                InstanceSSHConfig.provider == _PROVIDER,
                InstanceSSHConfig.instance_id.in_(server_ids),
            ).all()
            ssh_set = {c.instance_id for c in ssh_configs}
            for s in servers:
                s['ssh_configured'] = s['id'] in ssh_set
        else:
            for s in servers:
                s['local_tags'] = []
                s['ssh_configured'] = False

        return jsonify({'servers': servers})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/servers/<server_id>', methods=['GET'])
@login_required
@_hetzner_configured_required
def hetzner_get_server(server_id):
    try:
        server = hetzner_service.get_server(server_id, label=_server_label(server_id))
        return jsonify({'server': server})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/servers', methods=['POST'])
@login_required
@admin_required
@_hetzner_configured_required
def hetzner_create_server():
    data = request.get_json() or {}
    label = (data.get('label') or 'default').strip()
    name = (data.get('name') or '').strip()
    server_type = (data.get('server_type') or '').strip()
    image = (data.get('image') or '').strip()
    location = (data.get('location') or '').strip()
    ssh_keys = data.get('ssh_keys') or []
    user_data = data.get('user_data') or None

    if not name or not server_type or not image or not location:
        return jsonify({'error': 'name, server_type, image, and location are required'}), 400

    try:
        result = hetzner_service.create_server(
            label=label,
            name=name,
            server_type=server_type,
            image=image,
            location=location,
            ssh_keys=ssh_keys,
            user_data=user_data,
        )
        # Update cache so subsequent calls resolve label correctly
        hetzner_service._server_account_cache[result['id']] = label
        audit_service.log(
            'hetzner.create', 'hetzner', label, result['id'],
            {'name': name, 'server_type': server_type, 'image': image, 'location': location},
        )
        return jsonify({'server': result}), 201
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/servers/<server_id>/poweron', methods=['POST'])
@login_required
@_hetzner_configured_required
def hetzner_start_server(server_id):
    label = _server_label(server_id)
    try:
        result = hetzner_service.start_server(server_id, label=label)
        audit_service.log('hetzner.start', 'hetzner', label, server_id, {})
        return jsonify({'result': result})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/servers/<server_id>/poweroff', methods=['POST'])
@login_required
@_hetzner_configured_required
def hetzner_stop_server(server_id):
    label = _server_label(server_id)
    try:
        result = hetzner_service.stop_server(server_id, label=label)
        audit_service.log('hetzner.stop', 'hetzner', label, server_id, {})
        return jsonify({'result': result})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/servers/<server_id>/reboot', methods=['POST'])
@login_required
@_hetzner_configured_required
def hetzner_reboot_server(server_id):
    label = _server_label(server_id)
    try:
        result = hetzner_service.reboot_server(server_id, label=label)
        audit_service.log('hetzner.reboot', 'hetzner', label, server_id, {})
        return jsonify({'result': result})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/servers/<server_id>', methods=['DELETE'])
@login_required
@admin_required
@_hetzner_configured_required
def hetzner_delete_server(server_id):
    label = _server_label(server_id)
    try:
        result = hetzner_service.delete_server(server_id, label=label)
        # Clean up cached label + local tags + SSH config for this server
        hetzner_service._server_account_cache.pop(str(server_id), None)
        InstanceTag.query.filter_by(provider=_PROVIDER, instance_id=str(server_id)).delete()
        InstanceSSHConfig.query.filter_by(provider=_PROVIDER, instance_id=str(server_id)).delete()
        db.session.commit()
        audit_service.log('hetzner.delete', 'hetzner', label, server_id, {})
        return jsonify({'result': result})
    except Exception as e:
        db.session.rollback()
        return safe_error(e, 400)


# --- Lookups: locations, server types, images ---

@api_bp.route('/hetzner/locations', methods=['GET'])
@login_required
@_hetzner_configured_required
def hetzner_list_locations():
    label = request.args.get('label', 'default')
    try:
        locations = hetzner_service.list_locations(label=label)
        return jsonify({'locations': locations})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/server-types', methods=['GET'])
@login_required
@_hetzner_configured_required
def hetzner_list_server_types():
    label = request.args.get('label', 'default')
    try:
        types = hetzner_service.list_server_types(label=label)
        return jsonify({'server_types': types})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/images', methods=['GET'])
@login_required
@_hetzner_configured_required
def hetzner_list_images():
    label = request.args.get('label', 'default')
    image_type = request.args.get('type', 'system')
    try:
        images = hetzner_service.list_images(label=label, image_type=image_type)
        return jsonify({'images': images})
    except Exception as e:
        return safe_error(e, 400)


# --- Local Tags (provider-scoped) ---

@api_bp.route('/hetzner/tags', methods=['GET'])
@login_required
@_hetzner_configured_required
def hetzner_list_distinct_tags():
    try:
        rows = (db.session.query(InstanceTag.tag)
                .filter_by(provider=_PROVIDER)
                .distinct()
                .order_by(InstanceTag.tag)
                .all())
        return jsonify({'tags': [r[0] for r in rows]})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/servers/<server_id>/tags', methods=['GET'])
@login_required
@_hetzner_configured_required
def hetzner_get_server_tags(server_id):
    try:
        tags = InstanceTag.query.filter_by(provider=_PROVIDER, instance_id=str(server_id)).all()
        return jsonify({'tags': [t.to_dict() for t in tags]})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/servers/<server_id>/tags', methods=['POST'])
@login_required
@_hetzner_configured_required
def hetzner_add_server_tag(server_id):
    data = request.get_json() or {}
    tag = (data.get('tag') or '').strip()
    if not tag:
        return jsonify({'error': 'tag is required'}), 400

    existing = InstanceTag.query.filter_by(provider=_PROVIDER, instance_id=str(server_id), tag=tag).first()
    if existing:
        return jsonify({'tag': existing.to_dict()}), 200

    new_tag = InstanceTag(provider=_PROVIDER, instance_id=str(server_id), tag=tag)
    db.session.add(new_tag)
    db.session.commit()
    return jsonify({'tag': new_tag.to_dict()}), 201


@api_bp.route('/hetzner/servers/<server_id>/tags/<tag>', methods=['DELETE'])
@login_required
@_hetzner_configured_required
def hetzner_remove_server_tag(server_id, tag):
    existing = InstanceTag.query.filter_by(provider=_PROVIDER, instance_id=str(server_id), tag=tag).first()
    if not existing:
        return jsonify({'error': 'Tag not found'}), 404
    db.session.delete(existing)
    db.session.commit()
    return jsonify({'deleted': True})


# --- Local SSH configs (encrypted private keys for connecting IN to servers) ---

@api_bp.route('/hetzner/servers/<server_id>/ssh', methods=['GET'])
@login_required
@_hetzner_configured_required
def hetzner_get_ssh_config(server_id):
    try:
        config = InstanceSSHConfig.query.filter_by(provider=_PROVIDER, instance_id=str(server_id)).first()
        return jsonify({'ssh_config': config.to_dict() if config else None})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/servers/<server_id>/ssh', methods=['POST'])
@login_required
@admin_required
@_hetzner_configured_required
def hetzner_save_ssh_config(server_id):
    data = request.get_json() or {}
    ssh_username = (data.get('ssh_username') or 'root').strip()
    private_key = (data.get('private_key') or '').strip()
    use_public_ip = data.get('use_public_ip', True)
    key_label = (data.get('key_label') or '').strip()

    try:
        config = InstanceSSHConfig.query.filter_by(provider=_PROVIDER, instance_id=str(server_id)).first()
        if config:
            config.ssh_username = ssh_username
            config.use_public_ip = use_public_ip
            config.key_label = key_label
            if private_key:
                f = _get_fernet()
                config.encrypted_private_key = f.encrypt(private_key.encode()).decode()
        else:
            if not private_key:
                return jsonify({'error': 'private_key is required for new configurations'}), 400
            f = _get_fernet()
            config = InstanceSSHConfig(
                provider=_PROVIDER,
                instance_id=str(server_id),
                ssh_username=ssh_username,
                encrypted_private_key=f.encrypt(private_key.encode()).decode(),
                use_public_ip=use_public_ip,
                key_label=key_label,
            )
            db.session.add(config)
        db.session.commit()
        return jsonify({'ssh_config': config.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return safe_error(e, 400)


@api_bp.route('/hetzner/servers/<server_id>/ssh', methods=['DELETE'])
@login_required
@admin_required
@_hetzner_configured_required
def hetzner_delete_ssh_config(server_id):
    try:
        config = InstanceSSHConfig.query.filter_by(provider=_PROVIDER, instance_id=str(server_id)).first()
        if not config:
            return jsonify({'error': 'SSH config not found'}), 404
        db.session.delete(config)
        db.session.commit()
        return jsonify({'deleted': True})
    except Exception as e:
        db.session.rollback()
        return safe_error(e, 400)


# --- Hetzner project SSH keys (public keys uploaded to Hetzner) ---

@api_bp.route('/hetzner/ssh-keys', methods=['GET'])
@login_required
@_hetzner_configured_required
def hetzner_list_project_ssh_keys():
    label = request.args.get('label', 'default')
    try:
        keys = hetzner_service.list_ssh_keys(label=label)
        return jsonify({'ssh_keys': keys, 'label': label})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/ssh-keys', methods=['POST'])
@login_required
@admin_required
@_hetzner_configured_required
def hetzner_create_project_ssh_key():
    data = request.get_json() or {}
    label = (data.get('label') or 'default').strip()
    name = (data.get('name') or '').strip()
    public_key = (data.get('public_key') or '').strip()

    if not name or not public_key:
        return jsonify({'error': 'name and public_key are required'}), 400

    try:
        result = hetzner_service.create_ssh_key(label=label, name=name, public_key=public_key)
        audit_service.log('hetzner.ssh_key.create', 'hetzner', label, str(result['id']), {'name': name})
        return jsonify({'ssh_key': result, 'label': label}), 201
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/hetzner/ssh-keys/<int:key_id>', methods=['DELETE'])
@login_required
@admin_required
@_hetzner_configured_required
def hetzner_delete_project_ssh_key(key_id):
    label = request.args.get('label', 'default')
    try:
        result = hetzner_service.delete_ssh_key(label=label, key_id=key_id)
        audit_service.log('hetzner.ssh_key.delete', 'hetzner', label, str(key_id), {})
        return jsonify(result)
    except Exception as e:
        return safe_error(e, 400)

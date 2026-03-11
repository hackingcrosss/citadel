import logging
from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import cdn_service
from app.models.cdn_distribution import CdnDistribution
from app import db

_log = logging.getLogger(__name__)


@api_bp.route('/cdn/distributions', methods=['GET'])
@login_required
def cdn_list_distributions():
    try:
        records = CdnDistribution.query.order_by(CdnDistribution.created_at.desc()).all()
        return jsonify({'distributions': [r.to_dict() for r in records]})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/cdn/distributions', methods=['POST'])
@login_required
def cdn_create_distribution():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    provider = data.get('provider', '').strip()
    origin_host = data.get('origin_host', '').strip()
    origin_port = int(data.get('origin_port', 443))
    comment = data.get('comment', '').strip()
    account_label = data.get('account_label', 'default').strip() or 'default'
    resource_group = data.get('resource_group', '').strip()

    if not provider or not origin_host:
        return jsonify({'error': 'provider and origin_host are required'}), 400

    if provider not in ('cloudfront', 'azure_front_door'):
        return jsonify({'error': 'provider must be cloudfront or azure_front_door'}), 400

    if provider == 'azure_front_door' and not resource_group:
        return jsonify({'error': 'resource_group is required for Azure Front Door'}), 400

    try:
        if provider == 'cloudfront':
            result = cdn_service.create_cloudfront_distribution(
                origin_host, origin_port, comment, label=account_label
            )
        else:
            result = cdn_service.create_afd_distribution(
                resource_group, origin_host, origin_port, comment, label=account_label
            )

        dist = CdnDistribution(
            provider=provider,
            account_label=account_label,
            external_id=result['external_id'],
            domain=result['domain'],
            origin_host=origin_host,
            origin_port=origin_port,
            status=result['status'],
            comment=comment,
        )
        db.session.add(dist)
        db.session.commit()
        return jsonify({'distribution': dist.to_dict()}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/cdn/distributions/<int:dist_id>', methods=['GET'])
@login_required
def cdn_get_distribution(dist_id):
    dist = CdnDistribution.query.get_or_404(dist_id)
    return jsonify({'distribution': dist.to_dict()})


@api_bp.route('/cdn/distributions/<int:dist_id>/status', methods=['GET'])
@login_required
def cdn_get_distribution_status(dist_id):
    """Poll live status from the cloud provider and update local DB."""
    dist = CdnDistribution.query.get_or_404(dist_id)
    try:
        if dist.provider == 'cloudfront':
            live = cdn_service.get_cloudfront_distribution(dist.external_id, label=dist.account_label)
            new_status = live['status']
        else:
            # AFD — check endpoint deployment status
            parts = (dist.external_id or '').split('/')
            if len(parts) >= 3:
                rg, profile, endpoint = parts[0], parts[1], parts[2]
                client, _ = cdn_service._get_afd_client(label=dist.account_label)
                ep = client.afd_endpoints.get(rg, profile, endpoint)
                new_status = 'deployed' if str(ep.deployment_status or '').lower() == 'succeeded' else 'deploying'
            else:
                new_status = dist.status

        if dist.status != new_status:
            dist.status = new_status
            db.session.commit()

        return jsonify({'status': new_status, 'id': dist_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/cdn/distributions/<int:dist_id>', methods=['DELETE'])
@login_required
def cdn_delete_distribution(dist_id):
    """Teardown: disable (CloudFront only) → delete from provider → remove from DB."""
    dist = CdnDistribution.query.get_or_404(dist_id)
    try:
        if dist.provider == 'cloudfront':
            # Step 1: disable (required before delete)
            dist.status = 'disabling'
            db.session.commit()
            try:
                cf_status, etag = cdn_service.disable_cloudfront_distribution(
                    dist.external_id, label=dist.account_label
                )
            except Exception as exc:
                _log.warning("CloudFront disable failed: %s", exc)
                etag = None

            # Step 2: wait for Deployed state (distribution must be deployed to be deletable)
            # We attempt delete; if it fails because it's still InProgress, return a 409 so
            # the frontend can retry. We don't block the worker thread.
            if etag:
                try:
                    cdn_service.delete_cloudfront_distribution(
                        dist.external_id, etag, label=dist.account_label
                    )
                except Exception as exc:
                    err_str = str(exc)
                    if 'DistributionNotDisabled' in err_str or 'PreconditionFailed' in err_str:
                        dist.status = 'disabling'
                        db.session.commit()
                        return jsonify({'error': 'Distribution is still deploying. Try again in a few minutes.',
                                        'retry': True}), 409
                    raise

        elif dist.provider == 'azure_front_door':
            parts = (dist.external_id or '').split('/')
            if len(parts) >= 3:
                rg, profile, endpoint = parts[0], parts[1], parts[2]
                cdn_service.delete_afd_distribution(rg, profile, endpoint, label=dist.account_label)

        db.session.delete(dist)
        db.session.commit()
        return jsonify({'deleted': True, 'id': dist_id})

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import cdn_service
from app.models.cdn_distribution import CdnDistribution
from app import db
from app.utils.decorators import feature_required
from app.services.project_service import (
    build_project_tag_map,
    can_read,
    can_write,
    get_active_project,
    get_project_domain_names,
    get_project_resource_external_ids,
    tag_resource,
)
from app.models.project_resource import ProjectResource
from app.utils.errors import safe_error

_log = logging.getLogger(__name__)

_AFD_EXTERNAL_ID_RE = re.compile(r'^[A-Za-z0-9_.()\-]{1,90}/[A-Za-z0-9\-]{1,260}/[A-Za-z0-9\-]{1,260}$')
_CLOUDFRONT_EXTERNAL_ID_RE = re.compile(r'^[A-Z0-9]{8,32}$')


def _active_project_write_or_response():
    project = get_active_project(current_user)
    if not project:
        return None, (jsonify({'error': 'No active project selected'}), 400)
    if not can_write(current_user, project.id):
        return None, (jsonify({'error': 'Write access required for active project'}), 403)
    return project, None


def _host_matches_project_domains(host, project_id):
    host = (host or '').lower().rstrip('.')
    if not host:
        return False
    for domain in get_project_domain_names(project_id):
        domain = domain.lower().rstrip('.')
        if host == domain or host.endswith('.' + domain):
            return True
    return False


def _cdn_access_error(dist, write=False):
    if current_user.is_admin:
        return None
    if current_user.is_auditor and write:
        return (jsonify({'error': 'Auditors have read-only access'}), 403)

    resource = ProjectResource.query.filter_by(
        resource_type='cdn_dist', external_id=str(dist.id)
    ).first()
    if resource:
        allowed = can_write(current_user, resource.project_id) if write else can_read(current_user, resource.project_id)
        if allowed:
            return None
        return (jsonify({'error': 'CDN distribution is tagged to a project you cannot access'}), 403)

    if write:
        return (jsonify({'error': 'CDN distribution must be tagged to your project before modification'}), 403)

    active_project = get_active_project(current_user)
    if active_project and _host_matches_project_domains(dist.origin_host, active_project.id):
        return None
    return (jsonify({'error': 'CDN distribution is not in your active project'}), 403)


def _validate_external_id(provider, external_id):
    """Validate provider-specific CDN external identifiers before SDK calls."""
    external_id = (external_id or '').strip()
    if not external_id:
        return False, 'external_id is required'
    if provider == 'cloudfront' and '/' in external_id:
        return False, 'CloudFront external_id must not contain path separators'
    if provider == 'azure_front_door':
        if not _AFD_EXTERNAL_ID_RE.fullmatch(external_id):
            return False, 'Azure Front Door external_id must be resourceGroup/profile/endpoint'
        return True, None
    if provider == 'cloudfront':
        if not _CLOUDFRONT_EXTERNAL_ID_RE.fullmatch(external_id):
            return False, 'CloudFront external_id has invalid format'
        return True, None
    return False, 'provider must be cloudfront or azure_front_door'


def _afd_external_id_parts(external_id):
    ok, reason = _validate_external_id('azure_front_door', external_id)
    if not ok:
        raise ValueError(reason)
    return external_id.split('/', 2)


def _try_recover_creating_dist(dist):
    """Try to find a 'creating' distribution in the live cloud provider and
    recover its external_id, domain, and status.  Returns True if recovered."""
    try:
        if dist.provider == 'azure_front_door':
            live_dists = cdn_service.list_afd_all_accounts()
        elif dist.provider == 'cloudfront':
            live_dists = cdn_service.list_cf_all_accounts()
        else:
            return False

        # Match by origin_host (the only reliable link between local and cloud)
        for live in live_dists:
            if live.get('origin_host', '') == dist.origin_host and \
               live.get('account_label', 'default') == dist.account_label:
                dist.external_id = live['external_id']
                dist.domain = live.get('domain', '')
                dist.status = live.get('status', 'deployed')
                _log.info("Recovered stuck CDN dist id=%s → ext_id=%s domain=%s status=%s",
                          dist.id, dist.external_id, dist.domain, dist.status)
                return True
    except Exception as exc:
        _log.debug("Recovery lookup failed for dist id=%s: %s", dist.id, exc)
    return False


@api_bp.route('/cdn/distributions', methods=['GET'])
@login_required
@feature_required('cdn')
def cdn_list_distributions():
    try:
        # Start with locally tracked records
        records = CdnDistribution.query.order_by(CdnDistribution.created_at.desc()).all()
        tracked_by_ext_id = {r.external_id: r for r in records if r.external_id}

        # Enrich with project tags
        tag_map = build_project_tag_map('cdn_dist', [str(r.id) for r in records])
        result = []
        for r in records:
            d = r.to_dict()
            tag = tag_map.get(str(r.id))
            d['project_id'] = tag['project_id'] if tag else None
            d['project_code'] = tag['project_code'] if tag else None
            d['project_resource_id'] = tag['project_resource_id'] if tag else None
            result.append(d)

        # Discover live distributions from each provider in parallel with a timeout
        # so slow/unconfigured providers never block the response.
        live_dists = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(cdn_service.list_cf_all_accounts): 'cloudfront',
                pool.submit(cdn_service.list_afd_all_accounts): 'azure_front_door',
            }
            try:
                for future in as_completed(futures, timeout=15):
                    try:
                        live_dists.extend(future.result())
                    except Exception as exc:
                        _log.debug("CDN discovery skipped (%s): %s", futures[future], exc)
            except FuturesTimeoutError:
                _log.debug("CDN live discovery timed out — returning locally tracked records only")

        for live in live_dists:
            ext_id = live.get('external_id', '')
            if ext_id and ext_id not in tracked_by_ext_id:
                result.append({
                    'id': None,
                    'tracked': False,
                    'provider': live.get('provider'),
                    'account_label': live.get('account_label', 'default'),
                    'external_id': ext_id,
                    'domain': live.get('domain', ''),
                    'origin_host': live.get('origin_host', ''),
                    'origin_port': None,
                    'status': live.get('status', 'unknown'),
                    'comment': live.get('comment', ''),
                    'created_at': None,
                    'updated_at': None,
                })

        _auditor_unscoped = current_user.is_auditor and get_active_project(current_user) is None
        if not current_user.is_admin and not _auditor_unscoped:
            active_project = get_active_project(current_user)
            if active_project is None:
                result = []
            else:
                project_domains = get_project_domain_names(active_project.id)
                tagged_ids = get_project_resource_external_ids(active_project.id, 'cdn_dist')
                def _visible(d):
                    # Tagged to this project
                    if str(d.get('id') or '') in tagged_ids:
                        return True
                    # Origin host matches a project domain or subdomain
                    host = d.get('origin_host') or ''
                    for dom in project_domains:
                        if host == dom or host.endswith('.' + dom):
                            return True
                    return False
                result = [d for d in result if _visible(d)]

        return jsonify({'distributions': result})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/cdn/distributions/import', methods=['POST'])
@login_required
@feature_required('cdn')
def cdn_import_distribution():
    """Import an externally-created distribution into local tracking."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    provider = data.get('provider', '').strip()
    external_id = data.get('external_id', '').strip()
    ok, reason = _validate_external_id(provider, external_id)
    if not ok:
        return jsonify({'error': reason}), 400

    active_project, access_error = _active_project_write_or_response()
    if access_error:
        return access_error

    if CdnDistribution.query.filter_by(external_id=external_id).first():
        return jsonify({'error': 'Distribution already tracked'}), 409

    dist = CdnDistribution(
        provider=provider,
        account_label=data.get('account_label', 'default'),
        external_id=external_id,
        domain=data.get('domain', ''),
        origin_host=data.get('origin_host', ''),
        origin_port=data.get('origin_port') or 443,
        status=data.get('status', 'deployed'),
        comment=data.get('comment', ''),
    )
    db.session.add(dist)
    db.session.flush()
    tag_resource(active_project.id, 'cdn_dist', str(dist.id), dist.domain or dist.external_id, current_user.id)
    db.session.commit()
    return jsonify({'distribution': dist.to_dict()}), 201


@api_bp.route('/cdn/distributions', methods=['POST'])
@login_required
@feature_required('cdn')
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

    active_project, access_error = _active_project_write_or_response()
    if access_error:
        return access_error

    if not provider or not origin_host:
        return jsonify({'error': 'provider and origin_host are required'}), 400

    _HOSTNAME_RE = re.compile(r'^(?!-)([a-zA-Z0-9-]{1,63}(?<!-)\.)+[a-zA-Z]{2,}$')
    _IPV4_RE = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    if not _HOSTNAME_RE.match(origin_host) and not _IPV4_RE.match(origin_host):
        return jsonify({'error': f'Invalid origin host: {origin_host}'}), 400

    if provider not in ('cloudfront', 'azure_front_door'):
        return jsonify({'error': 'provider must be cloudfront or azure_front_door'}), 400

    if provider == 'azure_front_door' and not resource_group:
        return jsonify({'error': 'resource_group is required for Azure Front Door'}), 400

    # Pre-create a placeholder record so the frontend can track progress immediately
    dist = CdnDistribution(
        provider=provider,
        account_label=account_label,
        external_id=None,
        domain='',
        origin_host=origin_host,
        origin_port=origin_port,
        status='creating',
        comment=comment,
    )
    db.session.add(dist)
    db.session.commit()

    # Auto-tag to the creator's active project
    db.session.add(ProjectResource(
        project_id=active_project.id,
        resource_type='cdn_dist',
        external_id=str(dist.id),
        label=f'{provider} → {origin_host}',
        tagged_by_id=current_user.id,
    ))
    db.session.commit()

    # Dispatch background task and store task_id in external_id for status polling
    from app.tasks.cdn_tasks import create_cdn_distribution_task
    task = create_cdn_distribution_task.delay(
        dist.id, provider, origin_host, origin_port, comment, account_label, resource_group
    )
    dist.external_id = f'task:{task.id}'
    db.session.commit()

    return jsonify({'distribution': dist.to_dict(), 'task_id': task.id}), 202


@api_bp.route('/cdn/distributions/<int:dist_id>', methods=['GET'])
@login_required
@feature_required('cdn')
def cdn_get_distribution(dist_id):
    dist = CdnDistribution.query.get_or_404(dist_id)
    access_error = _cdn_access_error(dist)
    if access_error:
        return access_error
    return jsonify({'distribution': dist.to_dict()})


@api_bp.route('/cdn/distributions/<int:dist_id>/status', methods=['GET'])
@login_required
@feature_required('cdn')
def cdn_get_distribution_status(dist_id):
    """Poll live status from the cloud provider (or Celery task) and update local DB."""
    dist = CdnDistribution.query.get_or_404(dist_id)
    access_error = _cdn_access_error(dist)
    if access_error:
        return access_error

    # Task is still running (or just dispatched)
    if dist.status == 'creating':
        ext = dist.external_id or ''
        if ext.startswith('task:'):
            from celery.result import AsyncResult
            ar = AsyncResult(ext[5:])
            if ar.state == 'SUCCESS':
                # Task completed but DB update somehow missed — recover now
                result = ar.result or {}
                dist.external_id = result.get('external_id', ext)
                dist.domain = result.get('domain', '')
                dist.status = result.get('status', 'deploying')
                db.session.commit()
                return jsonify({'status': dist.status, 'id': dist_id})
            if ar.state == 'FAILURE':
                # Task failed but DB wasn't updated — recover error state
                dist.status = 'error'
                dist.external_id = f'error:{str(ar.result)[:400]}'
                db.session.commit()
                return jsonify({'status': 'error', 'id': dist_id, 'error': str(ar.result)})

            # Task is PENDING/STARTED/UNKNOWN — try to discover the live resource
            # from the cloud provider in case the task completed the cloud creation
            # but failed to update the DB (timeout, Redis restart, etc.)
            recovered = _try_recover_creating_dist(dist)
            if recovered:
                db.session.commit()
                return jsonify({'status': dist.status, 'id': dist_id,
                                'domain': dist.domain or '', 'recovered': True})

            return jsonify({'status': 'creating', 'id': dist_id, 'task_state': ar.state})
        return jsonify({'status': 'creating', 'id': dist_id, 'task_state': 'UNKNOWN'})

    # Task failed — error message may be stored in external_id or it may be a
    # real external_id (if the task partially succeeded before failing).
    if dist.status == 'error':
        ext = dist.external_id or ''
        if ext.startswith('error:'):
            error_msg = ext[6:]
        else:
            error_msg = 'Creation partially failed — some cloud resources may exist. Check your cloud account.'
        return jsonify({'status': 'error', 'id': dist_id, 'error': error_msg,
                        'domain': dist.domain or ''})

    # Normal case — poll live status from cloud provider
    try:
        if dist.provider == 'cloudfront':
            ok, reason = _validate_external_id('cloudfront', dist.external_id or '')
            if not ok:
                return jsonify({'error': reason}), 400
            live = cdn_service.get_cloudfront_distribution(dist.external_id, label=dist.account_label)
            new_status = live['status']
        else:
            # AFD — use provisioning_state (deployment_status is 'NotStarted' on new
            # endpoints that have had no explicit redeploy, which would wrongly stay
            # 'deploying' forever).
            rg, profile, endpoint = _afd_external_id_parts(dist.external_id or '')
            client, _ = cdn_service._get_afd_client(label=dist.account_label)
            ep = client.afd_endpoints.get(rg, profile, endpoint)
            prov = str(ep.provisioning_state or '').lower()
            new_status = 'deployed' if prov == 'succeeded' else 'deploying'

        if dist.status != new_status:
            dist.status = new_status
            db.session.commit()

        return jsonify({'status': new_status, 'id': dist_id})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/cdn/distributions/<int:dist_id>/force-refresh', methods=['POST'])
@login_required
@feature_required('cdn')
def cdn_force_refresh(dist_id):
    """Force-recover a stuck distribution by looking up the live cloud resource."""
    dist = CdnDistribution.query.get_or_404(dist_id)
    access_error = _cdn_access_error(dist, write=True)
    if access_error:
        return access_error

    if _try_recover_creating_dist(dist):
        db.session.commit()
        return jsonify({'distribution': dist.to_dict(), 'recovered': True})

    return jsonify({'error': 'Could not find matching live distribution. '
                    'Verify cloud credentials and that the resource still exists.'}), 404


@api_bp.route('/cdn/distributions/<int:dist_id>/probe', methods=['GET'])
@login_required
@feature_required('cdn')
def cdn_get_probe_settings(dist_id):
    """Return current health probe settings for an AFD distribution."""
    dist = CdnDistribution.query.get_or_404(dist_id)
    access_error = _cdn_access_error(dist)
    if access_error:
        return access_error
    if dist.provider != 'azure_front_door':
        return jsonify({'error': 'Not an Azure Front Door distribution'}), 400
    ok, reason = _validate_external_id('azure_front_door', dist.external_id or '')
    if not ok:
        return jsonify({'error': reason}), 400
    rg, profile, _endpoint = _afd_external_id_parts(dist.external_id or '')
    try:
        client, _ = cdn_service._get_afd_client(label=dist.account_label)
        ogs = list(client.afd_origin_groups.list_by_profile(rg, profile))
        if not ogs:
            return jsonify({'probe_protocol': 'NotSet', 'probe_path': '/', 'probe_interval': 100})
        hp = ogs[0].health_probe_settings
        return jsonify({
            'probe_protocol': str(hp.probe_protocol or 'NotSet') if hp else 'NotSet',
            'probe_path':     (hp.probe_path or '/') if hp else '/',
            'probe_interval': (hp.probe_interval_in_seconds or 100) if hp else 100,
        })
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/cdn/distributions/<int:dist_id>', methods=['PATCH'])
@login_required
@feature_required('cdn')
def cdn_update_distribution(dist_id):
    """Update origin_host, origin_port and/or comment on a tracked distribution."""
    dist = CdnDistribution.query.get_or_404(dist_id)
    access_error = _cdn_access_error(dist, write=True)
    if access_error:
        return access_error
    if dist.status == 'creating':
        return jsonify({'error': 'Cannot edit a distribution that is still being created'}), 409

    data = request.get_json() or {}
    origin_host    = data.get('origin_host', '').strip() or dist.origin_host
    origin_port    = int(data.get('origin_port') or dist.origin_port or 443)
    comment        = data.get('comment', dist.comment or '')
    probe_protocol = data.get('probe_protocol', '').strip()   # AFD only
    probe_path     = data.get('probe_path', '/').strip() or '/'
    probe_interval = int(data.get('probe_interval') or 100)

    try:
        if dist.provider == 'cloudfront':
            ok, reason = _validate_external_id('cloudfront', dist.external_id or '')
            if not ok:
                return jsonify({'error': reason}), 400
            cdn_service.update_cloudfront_origin(
                dist.external_id, origin_host, origin_port, comment, label=dist.account_label
            )
            dist.status = 'deploying'   # CF re-deploys after any config change
        else:
            rg, profile, _endpoint = _afd_external_id_parts(dist.external_id or '')
            cdn_service.update_afd_origin(
                rg, profile, origin_host, origin_port, label=dist.account_label
            )
            if probe_protocol:
                cdn_service.update_afd_health_probe(
                    rg, profile, probe_protocol, probe_path, probe_interval,
                    label=dist.account_label
                )

        dist.origin_host = origin_host
        dist.origin_port = origin_port
        dist.comment     = comment
        db.session.commit()
        return jsonify({'distribution': dist.to_dict()})

    except Exception as e:
        db.session.rollback()
        return safe_error(e, 400)


@api_bp.route('/cdn/distributions/<int:dist_id>', methods=['DELETE'])
@login_required
@feature_required('cdn')
def cdn_delete_distribution(dist_id):
    """Teardown: disable (CloudFront only) → delete from provider → remove from DB."""
    dist = CdnDistribution.query.get_or_404(dist_id)
    access_error = _cdn_access_error(dist, write=True)
    if access_error:
        return access_error
    try:
        # If the distribution is still being created by a background task, revoke the
        # task and just remove the DB record. The cloud resource may already have been
        # partially created; warn the user via the frontend.
        if dist.status == 'creating':
            ext = dist.external_id or ''
            if ext.startswith('task:'):
                try:
                    from celery.result import AsyncResult
                    AsyncResult(ext[5:]).revoke(terminate=True)
                except Exception as exc:
                    _log.warning("Could not revoke CDN creation task: %s", exc)
            db.session.delete(dist)
            db.session.commit()
            return jsonify({'deleted': True, 'id': dist_id, 'was_creating': True})

        if dist.provider == 'cloudfront':
            ok, reason = _validate_external_id('cloudfront', dist.external_id or '')
            if not ok:
                return jsonify({'error': reason}), 400
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
            rg, profile, endpoint = _afd_external_id_parts(dist.external_id or '')
            cdn_service.delete_afd_distribution(rg, profile, endpoint, label=dist.account_label)

        db.session.delete(dist)
        db.session.commit()
        return jsonify({'deleted': True, 'id': dist_id})

    except Exception as e:
        db.session.rollback()
        return safe_error(e, 400)

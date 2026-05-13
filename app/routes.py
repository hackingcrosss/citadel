import logging
import os
import re
from flask import render_template, redirect, url_for, request, flash, session
from flask_login import login_required, current_user, login_user, logout_user
from urllib.parse import urlparse, urljoin, unquote
from app import db
from app.models.user import User
from app.utils.decorators import admin_required, feature_required
from app.services import audit_service
from datetime import datetime


def _is_safe_next(target):
    r"""Tight allow-list for the login ?next parameter.

    Python's urlparse leaves several browser-equivalent off-origin payloads
    looking innocuous (backslashes, %5c, /\, ////host, mixed slash/backslash).
    Reject anything that, after URL-decoding, doesn't look like a strict
    same-origin path. Anything with a scheme, host, control char, backslash,
    or double-leading-slash variant gets blocked.
    """
    if not target:
        return False
    decoded = unquote(target)
    # Reject control / null / whitespace and backslash variants.
    if any(c in decoded for c in ('\\', '\r', '\n', '\t', '\0')):
        return False
    # Reject anything starting with a non-path prefix.
    if decoded.startswith('//') or decoded.startswith('/\\'):
        return False
    # Reject anything that's not anchored to the root path.
    if not decoded.startswith('/'):
        return False
    # Sanity: the joined-and-parsed URL must stay on the same origin.
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return (
        test.scheme in ('http', 'https')
        and ref.netloc == test.netloc
        and test.path.startswith('/')
        and not test.path.startswith('//')
    )

_log = logging.getLogger(__name__)

_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_WINDOW_SECONDS = 600  # 10-minute sliding window

def _redis_client():
    """Return a Redis client, or None if unavailable."""
    try:
        import redis as _redis
        return _redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'),
                               socket_connect_timeout=1, socket_timeout=1)
    except Exception:
        return None

def _is_rate_limited(ip):
    r = _redis_client()
    if r is None:
        return False
    try:
        val = r.get(f'login_fail:{ip}')
        return val is not None and int(val) >= _LOGIN_MAX_ATTEMPTS
    except Exception:
        return False

def _record_failure(ip):
    r = _redis_client()
    if r is None:
        return
    try:
        key = f'login_fail:{ip}'
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, _LOGIN_WINDOW_SECONDS)
        pipe.execute()
    except Exception:
        pass

def _clear_failures(ip):
    r = _redis_client()
    if r is None:
        return
    try:
        r.delete(f'login_fail:{ip}')
    except Exception:
        pass

def _check_password_complexity(password):
    """Return an error string if the password fails complexity rules, else None."""
    if len(password) < 12:
        return 'New password must be at least 12 characters long'
    if not re.search(r'[A-Z]', password):
        return 'New password must contain at least one uppercase letter'
    if not re.search(r'[a-z]', password):
        return 'New password must contain at least one lowercase letter'
    if not re.search(r'[0-9]', password):
        return 'New password must contain at least one digit'
    return None

def register_routes(app):
    @app.before_request
    def check_password_change():
        """Redirect authenticated users who must change their password."""
        if current_user.is_authenticated and current_user.must_change_password:
            allowed = ('change_password', 'login', 'logout', 'static')
            if request.endpoint and request.endpoint not in allowed:
                return redirect(url_for('change_password'))

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return redirect(url_for('login'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        return render_template('dashboard.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))

        if request.method == 'POST':
            client_ip = request.remote_addr or '0.0.0.0'

            if _is_rate_limited(client_ip):
                flash('Too many failed login attempts. Please try again later.', 'danger')
                return render_template('login.html')

            email = request.form.get('email')
            password = request.form.get('password')
            remember = request.form.get('remember', False)

            user = User.query.filter_by(email=email).first()

            if user and user.check_password(password):
                _clear_failures(client_ip)

                # Update last login
                user.last_login = datetime.utcnow()
                db.session.commit()

                login_user(user, remember=remember)

                # Force password change if flagged
                if user.must_change_password:
                    return redirect(url_for('change_password'))

                audit_service.log('auth.login', 'user', user.id, user.email)
                flash('Login successful!', 'success')
                next_page = request.args.get('next')
                # A-02: urlparse-only validation misses several browser-equivalent
                # off-origin payloads (backslashes, %5c, ////host, /\, etc.).
                # Use the strict allow-list helper instead.
                if not _is_safe_next(next_page):
                    next_page = None
                return redirect(next_page or url_for('dashboard'))
            else:
                _record_failure(client_ip)
                _log.warning('Failed login attempt for %r from %s', email, client_ip)
                audit_service.log('auth.login_failed', 'user', '', email or '', {'ip': client_ip})
                flash('Invalid email or password', 'danger')

        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('You have been logged out', 'info')
        return redirect(url_for('login'))

    @app.route('/change-password', methods=['GET', 'POST'])
    @login_required
    def change_password():
        if request.method == 'POST':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')

            # Validate current password
            if not current_user.check_password(current_password):
                flash('Current password is incorrect', 'danger')
                return render_template('change_password.html')

            # Validate new password complexity
            complexity_error = _check_password_complexity(new_password)
            if complexity_error:
                flash(complexity_error, 'danger')
                return render_template('change_password.html')

            if new_password != confirm_password:
                flash('New passwords do not match', 'danger')
                return render_template('change_password.html')

            # Don't allow same password
            if current_user.check_password(new_password):
                flash('New password must be different from current password', 'danger')
                return render_template('change_password.html')

            # Update password
            current_user.set_password(new_password)
            current_user.must_change_password = False
            db.session.commit()

            audit_service.log('auth.password_change', 'user', current_user.id, current_user.email)
            flash('Password changed successfully!', 'success')
            return redirect(url_for('dashboard'))

        return render_template('change_password.html')

    @app.route('/profile')
    @login_required
    def profile():
        return render_template('profile.html')

    @app.route('/domains')
    @login_required
    def domains():
        return render_template('domains.html')

    @app.route('/containers')
    @login_required
    def containers():
        return render_template('containers.html')

    @app.route('/email')
    @login_required
    def email():
        return render_template('email.html')

    @app.route('/npm')
    @login_required
    def npm():
        return render_template('npm.html')

    @app.route('/aws')
    @login_required
    def aws():
        return render_template('aws.html')

    @app.route('/azure')
    @login_required
    def azure():
        return render_template('azure.html')

    @app.route('/hetzner')
    @login_required
    def hetzner():
        from app.services.credential_service import get_account_labels
        if not get_account_labels('hetzner'):
            flash('Hetzner integration is not configured.', 'warning')
            return redirect(url_for('dashboard'))
        return render_template('hetzner.html')

    @app.route('/azure-dns')
    @login_required
    def azure_dns():
        return render_template('azure_dns.html')

    @app.route('/cdn')
    @login_required
    @feature_required('cdn')
    def cdn():
        return render_template('cdn.html')

    @app.route('/infra-map')
    @login_required
    @feature_required('infra_map')
    def infra_map():
        return render_template('infra_map.html')

    @app.route('/operations')
    @login_required
    def operations():
        if not current_user.can_write_infra:
            flash('RT Setup is not available for your role.', 'warning')
            return redirect(url_for('dashboard'))
        return render_template('operations.html')

    @app.route('/gophish')
    @login_required
    @feature_required('gophish')
    def gophish():
        return render_template('gophish.html')

    @app.route('/cobaltstrike')
    @login_required
    @feature_required('cobaltstrike')
    def cobaltstrike():
        return render_template('cobaltstrike.html')

    @app.route('/evilginx')
    @login_required
    @feature_required('evilginx')
    def evilginx():
        return render_template('evilginx.html')

    @app.route('/orchestration')
    @login_required
    def orchestration_mgmt():
        return render_template('orchestration.html')

    @app.route('/settings')
    @login_required
    @admin_required
    def settings():
        return render_template('settings.html')

    @app.route('/admin/users')
    @login_required
    @admin_required
    def admin_users():
        return render_template('admin_users.html')

    @app.route('/admin/license')
    @login_required
    @admin_required
    def admin_license():
        return render_template('admin_license.html')

    @app.route('/admin/audit')
    @login_required
    def admin_audit():
        if not (current_user.is_admin or current_user.is_auditor):
            flash('Admin or Auditor access required.', 'danger')
            return redirect(url_for('dashboard'))
        return render_template('admin_audit.html')

    @app.route('/admin/domain-pool')
    @login_required
    @admin_required
    def admin_domain_pool():
        return render_template('admin_domain_pool.html')

    # ── Citadel phase ─────────────────────────────────────────────────
    @app.route('/citadel/')
    @login_required
    def citadel_dashboard():
        return render_template('citadel_dashboard.html')

    @app.route('/citadel/projects')
    @login_required
    def citadel_projects():
        from app.services.plan_service import get_current_plan
        if not get_current_plan().is_enabled('projects'):
            flash('This feature is not available on your current plan.', 'warning')
            return redirect(url_for('citadel_dashboard'))
        if current_user.can_manage_projects:
            return render_template('admin_projects.html')
        return render_template('projects.html')

    @app.route('/citadel/companies')
    @login_required
    def citadel_companies():
        from app.services.plan_service import get_current_plan
        if not get_current_plan().is_enabled('companies'):
            flash('This feature is not available on your current plan.', 'warning')
            return redirect(url_for('citadel_dashboard'))
        if current_user.is_admin:
            return render_template('admin_companies.html')
        return render_template('company.html')

    # ── Legacy redirects (old Team routes → Citadel) ──────────────────
    @app.route('/admin/projects')
    @login_required
    def admin_projects():
        return redirect(url_for('citadel_projects'), 301)

    @app.route('/projects')
    @login_required
    def projects():
        return redirect(url_for('citadel_projects'), 301)

    @app.route('/admin/companies')
    @login_required
    def admin_companies():
        return redirect(url_for('citadel_companies'), 301)

    @app.route('/company')
    @login_required
    def company_detail():
        return redirect(url_for('citadel_companies'), 301)

    # ── Frontline phase ────────────────────────────────────────────────
    @app.route('/initial-access/')
    @login_required
    @feature_required('initial_access')
    def ia_dashboard():
        return render_template('ia_dashboard.html')

    @app.route('/initial-access/scope')
    @login_required
    @feature_required('initial_access')
    def ia_scope():
        return render_template('ia_scope.html')

    @app.route('/initial-access/recon')
    @login_required
    @feature_required('initial_access')
    def ia_recon():
        return render_template('ia_recon.html')

    @app.route('/initial-access/targets')
    @login_required
    @feature_required('initial_access')
    def ia_targets():
        return render_template('ia_targets.html')

    @app.route('/initial-access/campaigns')
    @login_required
    @feature_required('initial_access')
    def ia_campaigns():
        return render_template('ia_campaigns.html')

    @app.route('/initial-access/landing-pages')
    @login_required
    @feature_required('initial_access')
    def ia_landing_pages():
        return render_template('ia_landing_pages.html')

    @app.route('/initial-access/intel')
    @login_required
    @feature_required('initial_access')
    def ia_intel():
        return render_template('ia_intel.html')

    @app.route('/initial-access/email-templates')
    @login_required
    @feature_required('initial_access')
    def ia_email_templates():
        return render_template('ia_email_templates.html')

    @app.route('/initial-access/fofa')
    @login_required
    @feature_required('initial_access')
    def ia_fofa():
        return render_template('ia_fofa.html')

    @app.route('/initial-access/discoveries')
    @login_required
    @feature_required('initial_access')
    def ia_discoveries():
        return render_template('ia_discoveries.html')

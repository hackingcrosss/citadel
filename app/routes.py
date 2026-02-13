from flask import render_template, redirect, url_for, request, flash, session
from flask_login import login_required, current_user, login_user, logout_user
from app import db
from app.models.user import User
from datetime import datetime

def register_routes(app):
    @app.before_request
    def check_password_change():
        """Redirect authenticated users who must change their password."""
        if current_user.is_authenticated and current_user.must_change_password:
            allowed = ('change_password', 'logout', 'static')
            if request.endpoint and request.endpoint not in allowed:
                flash('Please change your password before continuing', 'warning')
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
            email = request.form.get('email')
            password = request.form.get('password')
            remember = request.form.get('remember', False)

            user = User.query.filter_by(email=email).first()

            if user and user.check_password(password):
                # Update last login
                user.last_login = datetime.utcnow()
                db.session.commit()

                login_user(user, remember=remember)

                # Check if this is default admin password
                if email == 'admin@infrared.local' and user.check_password('admin'):
                    flash('You are using the default password. Please change it immediately!', 'warning')
                    return redirect(url_for('change_password'))

                flash('Login successful!', 'success')
                next_page = request.args.get('next')
                return redirect(next_page if next_page else url_for('dashboard'))
            else:
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

            # Validate new password
            if len(new_password) < 8:
                flash('New password must be at least 8 characters long', 'danger')
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

            flash('Password changed successfully!', 'success')
            return redirect(url_for('dashboard'))

        return render_template('change_password.html')

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

    @app.route('/operations')
    @login_required
    def operations():
        return render_template('operations.html')

    @app.route('/gophish')
    @login_required
    def gophish():
        return render_template('gophish.html')

    @app.route('/cobaltstrike')
    @login_required
    def cobaltstrike():
        return render_template('cobaltstrike.html')

    @app.route('/settings')
    @login_required
    def settings():
        return render_template('settings.html')

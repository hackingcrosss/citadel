#!/usr/bin/env python3
"""
Initialize the Citadel database with default user and tables
Run this after starting the containers with: docker-compose exec web python init_db.py
"""

import os
import secrets
import string

from app import create_app, db
from app.models.user import User, validate_password_strength
from app.models.credential import Credential
from app.models.domain import Domain, DNSRecord
from app.models.instance_tag import InstanceTag
from app.models.instance_ssh_config import InstanceSSHConfig
from app.models.license import License
from app.models.project import Project, ProjectMember
from app.models.project_resource import ProjectResource
from app.models.cdn_distribution import CdnDistribution
from app.models.domain_tag import DomainGroomingTag
from app.models.email_grooming import EmailGroomingConfig
from app.models.email_grooming_log import EmailGroomingLog
from app.models.phishlet import Phishlet, PhishletDNSRecord


def _generate_bootstrap_password(length=24):
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*-_+='
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        if validate_password_strength(password) is None:
            return password


def init_database():
    app = create_app()
    
    with app.app_context():
        # Create all tables
        print("Creating database tables...")
        db.create_all()
        
        # Check if bootstrap admin user exists
        admin_email = os.getenv('INITIAL_ADMIN_EMAIL', 'admin@citadel.local').strip().lower()
        admin = User.query.filter_by(email=admin_email).first()
        
        if not admin:
            # Create a bootstrap admin without the historical admin/admin default.
            print("Creating bootstrap admin user...")
            bootstrap_password = os.getenv('INITIAL_ADMIN_PASSWORD') or _generate_bootstrap_password()
            password_error = validate_password_strength(bootstrap_password)
            if password_error:
                raise RuntimeError(f'INITIAL_ADMIN_PASSWORD is too weak: {password_error}')

            admin = User(
                email=admin_email,
                display_name='Administrator',
                role='admin',
                must_change_password=True  # Force password change on first login
            )
            admin.set_password(bootstrap_password)
            
            db.session.add(admin)
            db.session.commit()
            
            print("✓ Bootstrap admin user created")
            print(f"  Email: {admin_email}")
            if os.getenv('INITIAL_ADMIN_PASSWORD'):
                print("  Password: value supplied via INITIAL_ADMIN_PASSWORD")
            else:
                print(f"  One-time password: {bootstrap_password}")
            print("  ⚠️  You will be required to change the password on first login!")
        else:
            print("✓ Bootstrap admin user already exists")

        # Create default project if none exists
        if not Project.query.filter_by(code='DEFAULT').first():
            print("Creating default project...")
            # admin is guaranteed to exist at this point
            if not admin:
                admin = User.query.filter_by(email=admin_email).first()
            default_project = Project(
                name='Default',
                code='DEFAULT',
                description='Default project for unassigned resources.',
                status='active',
                created_by_id=admin.id,
            )
            db.session.add(default_project)
            db.session.flush()
            default_member = ProjectMember(
                project_id=default_project.id,
                user_id=admin.id,
                project_role='operator',
                added_by_id=admin.id,
            )
            db.session.add(default_member)
            db.session.commit()
            print("✓ Default project created (code: DEFAULT)")
        else:
            print("✓ Default project already exists")

        # Create default Community license if none exists
        if not License.query.first():
            print("Creating default Community license...")
            lic = License(tier='community', org_name='Citadel')
            db.session.add(lic)
            db.session.commit()
            print("✓ Default Community license created")
        else:
            print("✓ License record already exists")

        print("\n✓ Database initialization complete!")

if __name__ == '__main__':
    init_database()
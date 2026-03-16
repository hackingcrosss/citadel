#!/usr/bin/env python3
"""
Initialize the InfraRed database with default user and tables
Run this after starting the containers with: docker-compose exec web python init_db.py
"""

from app import create_app, db
from app.models.user import User
from app.models.credential import Credential
from app.models.domain import Domain, DNSRecord
from app.models.instance_tag import InstanceTag
from app.models.instance_ssh_config import InstanceSSHConfig
from app.models.license import License
from app.models.project import Project, ProjectMember
from app.models.project_resource import ProjectResource
from app.models.cdn_distribution import CdnDistribution
from app.models.domain_tag import DomainGroomingTag

def init_database():
    app = create_app()
    
    with app.app_context():
        # Create all tables
        print("Creating database tables...")
        db.create_all()
        
        # Check if admin user exists
        admin = User.query.filter_by(email='admin@infrared.local').first()
        
        if not admin:
            # Create default admin user
            print("Creating default admin user...")
            admin = User(
                email='admin@infrared.local',
                display_name='Administrator',
                role='admin',
                must_change_password=True  # Force password change on first login
            )
            admin.set_password('admin')
            
            db.session.add(admin)
            db.session.commit()
            
            print("✓ Default admin user created")
            print("  Email: admin@infrared.local")
            print("  Password: admin")
            print("  ⚠️  You will be required to change the password on first login!")
        else:
            print("✓ Admin user already exists")

        # Create default project if none exists
        if not Project.query.filter_by(code='DEFAULT').first():
            print("Creating default project...")
            # admin is guaranteed to exist at this point
            if not admin:
                admin = User.query.filter_by(email='admin@infrared.local').first()
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
            lic = License(tier='community', org_name='InfraRed')
            db.session.add(lic)
            db.session.commit()
            print("✓ Default Community license created")
        else:
            print("✓ License record already exists")

        print("\n✓ Database initialization complete!")

if __name__ == '__main__':
    init_database()
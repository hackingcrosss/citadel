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
                is_admin=True,
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
        
        print("\n✓ Database initialization complete!")

if __name__ == '__main__':
    init_database()
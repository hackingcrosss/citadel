#!/usr/bin/env python3
"""
One-time migration: create the license table and seed a Community license row.

Run inside the container:
    docker compose exec web python migrate_add_license.py

Safe to run multiple times (idempotent).
"""

from app import create_app, db
from app.models.license import License


def run():
    app = create_app()
    with app.app_context():
        print("Creating license table if not exists...")
        db.create_all()  # safe: only creates missing tables

        if License.query.first():
            print("✓ License record already exists — migration already applied.")
            return

        print("Inserting default Community license...")
        lic = License(tier='community', org_name='Citadel')
        db.session.add(lic)
        db.session.commit()
        print("✓ Community license created.")


if __name__ == '__main__':
    run()

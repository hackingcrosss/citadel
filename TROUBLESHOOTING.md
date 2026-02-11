# InfraRed - Troubleshooting Guide

## Login Internal Server Error

If you're getting an internal server error when trying to log in, follow these steps:

### 1. Check the logs
```bash
docker-compose logs -f web
```

### 2. Common Issues & Solutions

#### Issue: "User model not found" or "models have no attribute"
**Solution:** Make sure the User model is imported properly
```bash
# Inside the container
docker-compose exec web python
>>> from app.models.user import User
>>> User.query.all()
```

#### Issue: "No module named 'app.models.user'"
**Solution:** Ensure the `__init__.py` file exists in the models directory
```bash
docker-compose exec web ls -la app/models/
# Should show __init__.py
```

If missing, create it:
```bash
docker-compose exec web touch app/models/__init__.py
```

#### Issue: Database table doesn't exist
**Solution:** Initialize the database
```bash
docker-compose exec web python init_db.py
```

#### Issue: SECRET_KEY not set
**Solution:** Check your `.env` file has `SECRET_KEY` set
```bash
# Generate a new one
python -c "import secrets; print(secrets.token_hex(32))"
# Add to .env
```

#### Issue: Database connection error
**Solution:** Check PostgreSQL is running
```bash
docker-compose ps
# postgres should show "Up"

# Test connection
docker-compose exec postgres psql -U infrared -d infrared -c "SELECT 1;"
```

### 3. Complete Reset (if nothing else works)

```bash
# Stop everything
docker-compose down -v

# Remove old data
docker volume rm infrared_postgres_data

# Start fresh
docker-compose up -d

# Wait for postgres to be ready (about 10 seconds)
sleep 10

# Initialize database
docker-compose exec web python init_db.py
```

### 4. Verify Setup

After initialization, test in Python:
```bash
docker-compose exec web python
```

```python
from app import create_app, db
from app.models.user import User

app = create_app()
with app.app_context():
    # Check if user exists
    user = User.query.filter_by(email='admin@infrared.local').first()
    print(f"User found: {user}")
    print(f"User email: {user.email}")
    
    # Test password
    print(f"Password check: {user.check_password('admin')}")
```

If this works, login should work too.

### 5. Debug Login Flow

Add debug logging to routes.py temporarily:
```python
@app.route('/login', methods=['GET', 'POST'])
def login():
    print(f"Login request method: {request.method}")
    if request.method == 'POST':
        email = request.form.get('email')
        print(f"Attempting login for: {email}")
        # ... rest of code
```

Check logs:
```bash
docker-compose logs -f web | grep "Login"
```

### 6. Check Flask Debug Mode

Enable debug mode in `.env` temporarily:
```env
FLASK_ENV=development
FLASK_DEBUG=1
```

Restart:
```bash
docker-compose restart web
```

This will show detailed error messages in the browser.

## Password Change Flow

After fixing login, the flow is:
1. Login with `admin@infrared.local` / `admin`
2. Automatically redirected to `/change-password`
3. Enter current password: `admin`
4. Enter new password (minimum 8 characters)
5. Confirm new password
6. Click "Change Password"
7. Redirected to dashboard

The `must_change_password` flag is set to `True` for the default admin user and prevents access to any other page until the password is changed.
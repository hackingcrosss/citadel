# InfraRed - Red Team Infrastructure Management

A web application for managing red team infrastructure including domains, Docker containers, AWS EC2 instances, and Nginx Proxy Manager entries.

## Features

- 🌐 **Domain Management**: Manage DNS records, email configurations (Mailgun integration)
- 🐳 **Container Management**: Deploy and manage Docker containers
- ☁️ **AWS EC2 Monitoring**: Check status of EC2 instances
- 🔒 **Secure Credential Storage**: Encrypted API keys and credentials
- 📊 **Dashboard**: Real-time overview of your infrastructure

## Quick Start

### 1. Generate Encryption Keys

```bash
# Generate master encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Generate Flask secret key
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set:
- `MASTER_ENCRYPTION_KEY` - Use the Fernet key from step 1
- `SECRET_KEY` - Use the hex key from step 1

### 3. Start Services

```bash
docker-compose up -d
```

### 4. Initialize Database

```bash
docker-compose exec web python init_db.py
```

### 5. Access Application

Open http://localhost in your browser

**Default Credentials:**
- Email: `admin@infrared.local`
- Password: `admin`

⚠️ **Change the default password immediately after first login!**

## Development

### View Logs
```bash
docker-compose logs -f web
```

### Restart Services
```bash
docker-compose restart web
docker-compose restart celery
```

### Access Shell
```bash
docker-compose exec web bash
```

### Database Migrations
```bash
# Create migration
docker-compose exec web flask db migrate -m "description"

# Apply migration
docker-compose exec web flask db upgrade
```

### Stop Services
```bash
docker-compose down
```

## Architecture

- **Backend**: Flask (Python)
- **Database**: PostgreSQL with encrypted credentials
- **Task Queue**: Celery + Redis
- **Frontend**: Bootstrap 5 + vanilla JavaScript
- **Proxy**: Nginx

## Security

- All API credentials are encrypted using Fernet (AES-256) before storage
- Master encryption key stored as environment variable
- Flask sessions secured with secret key
- HTTPS recommended for production (configure nginx with SSL certificates)

## Configuration

API credentials are configured in the Settings page:
- AWS (Access Key ID, Secret Access Key)
- Cloudflare (API Token, Zone ID)
- Mailgun (API Key, Domain)
- Nginx Proxy Manager (API URL, Token)

## Production Deployment

1. Use strong encryption keys (not the examples)
2. Configure HTTPS/SSL certificates
3. Change default admin password
4. Set up firewall rules
5. Enable 2FA for admin accounts
6. Regular backups of PostgreSQL database
7. Monitor logs for security issues

## License

For red team operations only. Use responsibly and with proper authorization.
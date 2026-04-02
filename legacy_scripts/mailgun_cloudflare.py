import argparse
import os
import requests
from dotenv import load_dotenv
from cloudflare import Cloudflare

# Load environment variables from .env file
load_dotenv()

# Set up argument parser
parser = argparse.ArgumentParser(description='Add domain to Mailgun and retrieve DNS records')
parser.add_argument('-d', '--domain', required=True, help='Domain name to add to Mailgun (e.g., mail.example.com)')
parser.add_argument('-r', '--region', default='eu', choices=['us', 'eu'], help='Mailgun region (us or eu)')
parser.add_argument('-z', '--zone-id', help='Cloudflare Zone ID (optional, for auto-creating DNS records)')
parser.add_argument('--add-to-cloudflare', action='store_true', help='Automatically add DNS records to Cloudflare')
args = parser.parse_args()

# Get Mailgun API key from environment
MAILGUN_API_KEY = os.getenv('MAILGUN_API_KEY')
if not MAILGUN_API_KEY:
    print("Error: MAILGUN_API_KEY not found in .env file")
    print("Please create a .env file with: MAILGUN_API_KEY=your_api_key_here")
    exit(1)

# Initialize Cloudflare client if needed
cf = None
if args.add_to_cloudflare:
    if not args.zone_id:
        print("Error: --zone-id is required when using --add-to-cloudflare")
        exit(1)

    CF_API_TOKEN = os.getenv('CF_API_TOKEN')
    if not CF_API_TOKEN:
        print("Error: CF_API_TOKEN not found in .env file")
        print("Please add CF_API_TOKEN to your .env file")
        exit(1)

    cf = Cloudflare(api_token=CF_API_TOKEN)

# Set Mailgun API base URL based on region
if args.region == 'eu':
    MAILGUN_API_BASE = "https://api.eu.mailgun.net/v3"
else:
    MAILGUN_API_BASE = "https://api.mailgun.net/v3"

# Authentication
auth = ("api", MAILGUN_API_KEY)

print(f"Checking if domain '{args.domain}' exists in Mailgun ({args.region.upper()} region):")
print("-" * 50)

# Check if domain already exists
domain_exists = False
try:
    response = requests.get(
        f"{MAILGUN_API_BASE}/domains/{args.domain}",
        auth=auth
    )

    if response.status_code == 200:
        print(f"✓ Domain '{args.domain}' already exists in Mailgun")
        domain_exists = True
    elif response.status_code == 404:
        print(f"ℹ Domain '{args.domain}' not found, will create it")
        domain_exists = False
    else:
        print(f"⚠ Unexpected response while checking domain. Status code: {response.status_code}")

except Exception as e:
    print(f"⚠ Error checking domain existence: {str(e)}")
    print("Will attempt to create domain...")

print("-" * 50)

# Add domain to Mailgun if it doesn't exist
if not domain_exists:
    print(f"\nAdding domain '{args.domain}' to Mailgun:")
    print("-" * 50)

    try:
        response = requests.post(
            f"{MAILGUN_API_BASE}/domains",
            auth=auth,
            data={
                'name': args.domain,
                'spam_action': 'disabled',  # Options: disabled, block, tag
                'wildcard': False,
                'force_dkim_authority': True,
                'dkim_key_size': 2048,
                'ips': []  # Empty for shared IP pool
            }
        )

        if response.status_code == 200:
            print(f"✓ Domain '{args.domain}' added successfully to Mailgun")
        else:
            print(f"✗ Failed to add domain. Status code: {response.status_code}")
            print(f"Response: {response.text}")
            exit(1)

    except Exception as e:
        print(f"✗ Error adding domain: {str(e)}")
        exit(1)

    print("-" * 50)

# Retrieve DNS records for the domain
print(f"\nRetrieving DNS records for '{args.domain}':")
print("-" * 50)

try:
    response = requests.get(
        f"{MAILGUN_API_BASE}/domains/{args.domain}",
        auth=auth
    )

    if response.status_code == 200:
        domain_info = response.json()

        # Extract DNS records - they're at the root level, not nested under 'domain'
        sending_records = domain_info.get('sending_dns_records', [])
        receiving_records = domain_info.get('receiving_dns_records', [])

        print("\n📧 SENDING DNS RECORDS (SPF, DKIM):")
        print("=" * 50)
        for record in sending_records:
            record_type = record.get('record_type')
            name = record.get('name', '')
            value = record.get('value', '')
            priority = record.get('priority', '')

            print(f"\nType: {record_type}")
            print(f"Name: {name}")
            if priority:
                print(f"Priority: {priority}")
            print(f"Value: {value}")
            print(f"Valid: {record.get('valid', 'unknown')}")

        print("\n" + "=" * 50)
        print("\n📬 RECEIVING DNS RECORDS (MX):")
        print("=" * 50)
        for record in receiving_records:
            record_type = record.get('record_type')
            name = record.get('name', '')
            value = record.get('value', '')
            priority = record.get('priority', '')

            print(f"\nType: {record_type}")
            print(f"Name: {name}")
            if priority:
                print(f"Priority: {priority}")
            print(f"Value: {value}")
            print(f"Valid: {record.get('valid', 'unknown')}")

        print("\n" + "=" * 50)
        print("\n📋 SUMMARY:")
        print("-" * 50)
        print(f"Total sending records: {len(sending_records)}")
        print(f"Total receiving records: {len(receiving_records)}")

        # Add records to Cloudflare if requested
        if args.add_to_cloudflare and cf:
            print("\n" + "=" * 50)
            print("\n🌐 Adding DNS records to Cloudflare:")
            print("-" * 50)

            records_created = 0
            records_failed = 0

            # Add sending records (SPF, DKIM, CNAME)
            for record in sending_records:
                record_type = record.get('record_type')
                name = record.get('name', '')
                value = record.get('value', '')

                try:
                    cf.dns.records.create(
                        zone_id=args.zone_id,
                        type=record_type,
                        name=name,
                        content=value,
                        ttl=1,  # Auto TTL
                        proxied=False  # DNS records for email should not be proxied
                    )
                    print(f"✓ Created {record_type} record: {name}")
                    records_created += 1

                except Exception as e:
                    error_message = str(e)
                    if "already exists" in error_message.lower():
                        print(f"⚠ {record_type} record already exists: {name}")
                    else:
                        print(f"✗ Failed to create {record_type} record {name}: {error_message}")
                        records_failed += 1

            # Add receiving records (MX)
            for record in receiving_records:
                record_type = record.get('record_type')
                name = args.domain  # MX records use the domain itself
                value = record.get('value', '')
                priority = record.get('priority', '10')

                try:
                    cf.dns.records.create(
                        zone_id=args.zone_id,
                        type=record_type,
                        name=name,
                        content=value,
                        priority=int(priority),
                        ttl=1,  # Auto TTL
                        proxied=False  # DNS records for email should not be proxied
                    )
                    print(f"✓ Created {record_type} record: {name} (priority: {priority}) -> {value}")
                    records_created += 1

                except Exception as e:
                    error_message = str(e)
                    if "already exists" in error_message.lower():
                        print(f"⚠ {record_type} record already exists: {name} -> {value}")
                    else:
                        print(f"✗ Failed to create {record_type} record {name}: {error_message}")
                        records_failed += 1

            print("\n" + "-" * 50)
            print(f"📊 Cloudflare Summary: {records_created} created, {records_failed} failed")
        else:
            print(f"\n⚠️  Add these DNS records to your domain's DNS settings")

        print(f"⚠️  It may take up to 48 hours for DNS changes to propagate")
        print(f"⚠️  You can verify the records in Mailgun dashboard after propagation")

    else:
        print(f"✗ Failed to retrieve DNS records. Status code: {response.status_code}")
        print(f"Response: {response.text}")

except Exception as e:
    print(f"✗ Error retrieving DNS records: {str(e)}")

print("\n" + "-" * 50)
print("Done!")
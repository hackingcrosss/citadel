import yaml
import argparse
import os
from dotenv import load_dotenv
from cloudflare import Cloudflare

# Load environment variables from .env file
load_dotenv()

# Set up argument parser
parser = argparse.ArgumentParser(description='Parse YAML phishlet file and create Cloudflare DNS records')
parser.add_argument('-p', '--phishlet', required=True, help='Path to the phishlet YAML file')
parser.add_argument('-z', '--zone-id', required=True, help='Cloudflare Zone ID')
parser.add_argument('-d', '--domain', required=True, help='Your domain name (e.g., example.com)')
parser.add_argument('-i', '--ip', required=True, help='IP address for A records')
args = parser.parse_args()

# Get Cloudflare API token from environment
CF_API_TOKEN = os.getenv('CF_API_TOKEN')
if not CF_API_TOKEN:
    print("Error: CF_API_TOKEN not found in .env file")
    print("Please create a .env file with: CF_API_TOKEN=your_token_here")
    exit(1)

# Initialize Cloudflare client
cf = Cloudflare(api_token=CF_API_TOKEN)

# Read from YAML file
try:
    with open(args.phishlet, 'r') as file:
        data = yaml.safe_load(file)
except FileNotFoundError:
    print(f"Error: File '{args.phishlet}' not found")
    exit(1)
except yaml.YAMLError as e:
    print(f"Error parsing YAML file: {e}")
    exit(1)

# Extract proxy_hosts
proxy_hosts = data.get('proxy_hosts', [])

if not proxy_hosts:
    print("Warning: No proxy_hosts found in the YAML file")
    exit(0)

print("Creating DNS records in Cloudflare:")
print("-" * 50)

created_domains = []

# Create A records for each proxy host
for host in proxy_hosts:
    phish_sub = host.get('phish_sub')
    
    if not phish_sub:
        print("⚠ Skipping entry with no phish_sub value")
        continue
    
    # Create the full domain name
    record_name = f"{phish_sub}.{args.domain}" if phish_sub != '@' else args.domain
    
    try:
        # Create the DNS record using Cloudflare SDK
        response = cf.dns.records.create(
            zone_id=args.zone_id,
            type='A',
            name=record_name,
            content=args.ip,
            ttl=1,  # Auto TTL
            proxied=True  # Enable Cloudflare proxy (orange cloud)
        )
        
        print(f"✓ Created A record: {record_name} -> {args.ip}")
        created_domains.append(record_name)
        
    except Exception as e:
        error_message = str(e)
        if "already exists" in error_message.lower():
            print(f"⚠ Record already exists: {record_name}")
            created_domains.append(record_name)  # Still add to list for bot protection
        else:
            print(f"✗ Failed to create {record_name}: {error_message}")

print("-" * 50)

# Enable bot protection for all created domains with a single rule
if created_domains:
    print("\nEnabling bot protection for all domains:")
    print("-" * 50)
    
    try:
        # Create a single WAF custom rule for all domains using Ruleset Engine
        # Build expression that matches any of the created domains
        domain_expressions = ' or '.join([f'(http.host eq "{domain}")' for domain in created_domains])
        full_expression = f'({domain_expressions}) and (cf.client.bot)'
        
        # Get the zone's rulesets to find the WAF custom rules phase
        rulesets = cf.rulesets.list(zone_id=args.zone_id)
        
        # Look for existing http_request_firewall_custom ruleset
        custom_ruleset = None
        for ruleset in rulesets:
            if ruleset.phase == 'http_request_firewall_custom':
                custom_ruleset = ruleset
                break
        
        # Create the rule in the custom ruleset
        if custom_ruleset:
            cf.rulesets.rules.create(
                ruleset_id=custom_ruleset.id,
                zone_id=args.zone_id,
                action='managed_challenge',
                expression=full_expression,
                description=f'Bot protection for phishlet domains: {", ".join(created_domains)}',
                enabled=True
            )
        else:
            # If no custom ruleset exists, create one with the rule
            cf.rulesets.create(
                zone_id=args.zone_id,
                phase='http_request_firewall_custom',
                name='Custom Firewall Rules',
                kind='zone',
                rules=[{
                    'action': 'managed_challenge',
                    'expression': full_expression,
                    'description': f'Bot protection for phishlet domains: {", ".join(created_domains)}',
                    'enabled': True
                }]
            )
        
        print(f"✓ Enabled bot protection for {len(created_domains)} domain(s):")
        for domain in created_domains:
            print(f"  - {domain}")
        
    except Exception as e:
        error_message = str(e)
        print(f"✗ Failed to enable bot protection: {error_message}")
    
    print("-" * 50)

print("Done!")

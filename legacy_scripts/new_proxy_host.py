#!/usr/bin/env python3
"""
Nginx Proxy Manager - Proxy Host Creator
Creates a new proxy host given a domain and target URL
"""

import requests
import argparse
import sys
import os
from urllib.parse import urlparse
from dotenv import load_dotenv


class NPMClient:
    def __init__(self, npm_url, email, password):
        self.base_url = npm_url.rstrip('/')
        self.email = email
        self.password = password
        self.token = None
        
    def authenticate(self):
        """Authenticate and get API token"""
        url = f"{self.base_url}/api/tokens"
        payload = {
            "identity": self.email,
            "secret": self.password
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            self.token = response.json()['token']
            print("✓ Authentication successful")
            return True
        except requests.exceptions.RequestException as e:
            print(f"✗ Authentication failed: {e}")
            return False
    
    def get_access_lists(self):
        """Fetch all available access lists"""
        if not self.token:
            print("✗ Not authenticated")
            return None
        
        url = f"{self.base_url}/api/nginx/access-lists"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"✗ Failed to fetch access lists: {e}")
            return None
    
    def create_proxy_host(self, domain, target_url, access_list_id=0):
        """Create a new proxy host"""
        if not self.token:
            print("✗ Not authenticated")
            return False
        
        # Parse target URL
        parsed = urlparse(target_url)
        scheme = parsed.scheme if parsed.scheme else 'http'
        host = parsed.hostname if parsed.hostname else parsed.path
        port = parsed.port if parsed.port else (443 if scheme == 'https' else 80)
        
        url = f"{self.base_url}/api/nginx/proxy-hosts"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "domain_names": [domain],
            "forward_scheme": scheme,
            "forward_host": host,
            "forward_port": port,
            "access_list_id": access_list_id,
            "certificate_id": 0,
            "ssl_forced": 0,
            "block_exploits": 1,
            "caching_enabled": 0,
            "allow_websocket_upgrade": 1,
            "http2_support": 1,
            "hsts_enabled": 0,
            "hsts_subdomains": 0,
            "meta": {
                "letsencrypt_agree": False,
                "dns_challenge": False
            },
            "advanced_config": "",
            "locations": []
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            print(f"✓ Proxy host created successfully")
            print(f"  ID: {result['id']}")
            print(f"  Domain: {domain}")
            print(f"  Target: {scheme}://{host}:{port}")
            if access_list_id > 0:
                print(f"  Access List ID: {access_list_id}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"✗ Failed to create proxy host: {e}")
            if hasattr(e.response, 'text'):
                print(f"  Response: {e.response.text}")
            return False


def create_cloudflare_record(domain, target_ip, zone_id, api_token):
    """Create a Cloudflare DNS A record"""
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "type": "A",
        "name": domain,
        "content": target_ip,
        "ttl": 1,  # Auto
        "proxied": True  # Enable Cloudflare proxy (orange cloud)
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        print(f"✓ Cloudflare DNS record created successfully")
        print(f"  ID: {result['result']['id']}")
        print(f"  Name: {result['result']['name']}")
        print(f"  IP: {result['result']['content']}")
        print(f"  Proxied: {result['result']['proxied']}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"✗ Failed to create Cloudflare DNS record: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_data = e.response.json()
                if 'errors' in error_data:
                    for error in error_data['errors']:
                        print(f"  Error: {error.get('message', 'Unknown error')}")
            except:
                print(f"  Response: {e.response.text}")
        return False


def main():
    # Load environment variables from .env file
    load_dotenv()
    
    parser = argparse.ArgumentParser(
        description='Create Nginx Proxy Manager proxy hosts via API'
    )
    parser.add_argument('-t','--target', required=True, help='Target URL (e.g., http://192.168.1.100:8080 or https://myapp)')
    parser.add_argument('-d', '--domain', required=True, help='Your domain name (e.g., example.com)')
    parser.add_argument('--add-to-cloudflare', action='store_true', help='Create Cloudflare DNS A record pointing to server IP')
    parser.add_argument('-z', '--zone-id', help='Cloudflare Zone ID (required with --add-to-cloudflare)')
    parser.add_argument('-i', '--ip', help='IP address for A records (required with --add-to-cloudflare)')

    # Optionals and configurable through .env
    parser.add_argument('--npm-url', default=os.getenv('NPM_URL', 'http://localhost:81'), help='NPM URL (default: from NPM_URL env or http://localhost:81)')
    parser.add_argument('--email', default=os.getenv('NPM_EMAIL', 'admin@example.com'), help='NPM admin email (default: from NPM_EMAIL env or admin@example.com)')
    parser.add_argument('--password', default=os.getenv('NPM_PASSWORD', 'changeme'), help='NPM admin password (default: from NPM_PASSWORD env or changeme)')
    parser.add_argument('--cf-api-token', default=os.getenv('CF_API_TOKEN'), help='Cloudflare API Token (default: from CF_API_TOKEN env)')
    
    # Optionals
    parser.add_argument('--access-list', type=int, default=0, help='Access list ID to apply (default: 0 for none)')
    parser.add_argument('--list-access-lists', action='store_true', help='List all available access lists and exit')

    
    args = parser.parse_args()
    
    # Validate Cloudflare arguments if --add-to-cloudflare is set
    if args.add_to_cloudflare:
        missing = []
        if not args.zone_id:
            missing.append("--zone-id (-z)")
        if not args.ip:
            missing.append("--ip (-i)")
        if not args.cf_api_token:
            missing.append("--cf-api-token or CF_API_TOKEN env variable")
        
        if missing:
            parser.error(f"--add-to-cloudflare requires: {', '.join(missing)}")
    
    # Create client and authenticate
    client = NPMClient(args.npm_url, args.email, args.password)
    
    if not client.authenticate():
        sys.exit(1)
    
    # List access lists if requested
    if args.list_access_lists:
        access_lists = client.get_access_lists()
        if access_lists:
            print("\nAvailable Access Lists:")
            print("-" * 60)
            for al in access_lists:
                print(f"ID: {al['id']}")
                print(f"  Name: {al['name']}")
                if 'items' in al and al['items']:
                    print(f"  Rules: {len(al['items'])} item(s)")
                print()
        sys.exit(0)
    
    # Create Cloudflare DNS record if requested
    if args.add_to_cloudflare:
        if not create_cloudflare_record(args.domain, args.ip, args.zone_id, args.cf_api_token):
            sys.exit(1)
        print()
    
    # Create proxy host
    if not client.create_proxy_host(args.domain, args.target, args.access_list):
        sys.exit(1)
    
    print("\n✓ Done!")


if __name__ == "__main__":
    main()
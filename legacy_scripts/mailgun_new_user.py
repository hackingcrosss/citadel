import os
import requests
import secrets
import string
from dotenv import load_dotenv
import argparse
import json

def generate_password(length=20):
    """
    Generate a secure random password.
    
    Args:
        length: Length of the password (default: 20)
    
    Returns:
        Randomly generated password string
    """
    alphabet = string.ascii_letters + string.digits + string.punctuation
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password

def create_mailgun_credentials(domain, email_address, password, api_key, api_base_url):
    """
    Create SMTP credentials for a new email address in Mailgun.
    
    Args:
        domain: Your verified Mailgun domain
        email_address: The full email address to create (e.g., user@yourdomain.com)
        password: Password for the SMTP credentials
        api_key: Your Mailgun API key
        api_base_url: Mailgun API base URL (US or EU)
    
    Returns:
        Dictionary with credential information or None on failure
    """
    url = f"{api_base_url}/v3/domains/{domain}/credentials"
    
    data = {
        "login": email_address,
        "password": password
    }
    
    try:
        response = requests.post(
            url,
            auth=("api", api_key),
            data=data
        )
        
        if response.status_code == 200:
            print(f"✓ Successfully created credentials for: {email_address}")
            return response.json()
        else:
            print(f"✗ Error creating credentials:")
            print(f"  Status Code: {response.status_code}")
            print(f"  Response: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"✗ Request failed: {e}")
        return None

def get_gophish_sending_profiles(gophish_url, gophish_api_key):
    """
    Get all sending profiles from GoPhish.
    
    Args:
        gophish_url: GoPhish instance URL
        gophish_api_key: GoPhish API key
    
    Returns:
        List of sending profiles or None on failure
    """
    url = f"{gophish_url}/api/smtp/"
    headers = {"Authorization": gophish_api_key}
    
    try:
        response = requests.get(url, headers=headers, verify=False)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"✗ Error fetching GoPhish sending profiles:")
            print(f"  Status Code: {response.status_code}")
            print(f"  Response: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"✗ Request failed: {e}")
        return None

def update_gophish_sending_profile(gophish_url, gophish_api_key, profile_id, email, password, smtp_server):
    """
    Update a GoPhish sending profile with new SMTP credentials.
    
    Args:
        gophish_url: GoPhish instance URL
        gophish_api_key: GoPhish API key
        profile_id: ID of the sending profile to update
        email: SMTP username (email address)
        password: SMTP password
        smtp_server: SMTP server address
    
    Returns:
        Updated profile data or None on failure
    """
    url = f"{gophish_url}/api/smtp/{profile_id}"
    headers = {
        "Authorization": gophish_api_key,
        "Content-Type": "application/json"
    }
    
    # First get the current profile
    try:
        response = requests.get(url, headers=headers, verify=False)
        if response.status_code != 200:
            print(f"✗ Error fetching profile {profile_id}")
            return None
        
        profile = response.json()
        
        # Update the SMTP credentials
        profile['username'] = email
        profile['password'] = password
        profile['host'] = f"{smtp_server}:587"
        profile['from_address'] = email
        
        # Update the profile
        response = requests.put(url, headers=headers, json=profile, verify=False)
        
        if response.status_code == 200:
            print(f"✓ Successfully updated GoPhish sending profile: {profile['name']}")
            return response.json()
        else:
            print(f"✗ Error updating GoPhish sending profile:")
            print(f"  Status Code: {response.status_code}")
            print(f"  Response: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"✗ Request failed: {e}")
        return None

def check_gophish_profile_exists(gophish_url, gophish_api_key, profile_name):
    """
    Check if a GoPhish sending profile with the given name already exists.
    
    Args:
        gophish_url: GoPhish instance URL
        gophish_api_key: GoPhish API key
        profile_name: Name to check for
    
    Returns:
        Profile data if exists, None otherwise
    """
    profiles = get_gophish_sending_profiles(gophish_url, gophish_api_key)
    
    if profiles is None:
        return None
    
    for profile in profiles:
        if profile.get('name') == profile_name:
            return profile
    
    return None

def create_gophish_sending_profile(gophish_url, gophish_api_key, name, email, password, smtp_server):
    """
    Create a new GoPhish sending profile with SMTP credentials.
    
    Args:
        gophish_url: GoPhish instance URL
        gophish_api_key: GoPhish API key
        name: Name for the sending profile
        email: SMTP username (email address)
        password: SMTP password
        smtp_server: SMTP server address
    
    Returns:
        Created profile data or None on failure
    """
    url = f"{gophish_url}/api/smtp/"
    headers = {
        "Authorization": gophish_api_key,
        "Content-Type": "application/json"
    }
    
    profile_data = {
        "name": name,
        "username": email,
        "password": password,
        "host": f"{smtp_server}:587",
        "from_address": email,
        "interface_type": "SMTP",
        "ignore_cert_errors": True
    }
    
    try:
        response = requests.post(url, headers=headers, json=profile_data, verify=False)
        
        if response.status_code == 201:
            print(f"✓ Successfully created GoPhish sending profile: {name}")
            return response.json()
        else:
            print(f"✗ Error creating GoPhish sending profile:")
            print(f"  Status Code: {response.status_code}")
            print(f"  Response: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"✗ Request failed: {e}")
        return None

def print_credentials(email, password, api_key, domain, api_base_url, region):
    """
    Print all credentials in a formatted way.
    
    Args:
        email: Email address created
        password: Password for SMTP
        api_key: Mailgun API key
        domain: Mailgun domain
        api_base_url: Mailgun API base URL
        region: Region (us or eu)
    """
    # Set SMTP server based on region
    smtp_servers = {
        'us': 'smtp.mailgun.org',
        'eu': 'smtp.eu.mailgun.org'
    }
    smtp_server = smtp_servers[region]
    
    print("\n" + "="*70)
    print("SMTP SERVER CONFIGURATION")
    print("="*70)
    print(f"Server:           {smtp_server}")
    print(f"Port (TLS):       587")
    print(f"Port (SSL):       465")
    print(f"Username:         {email}")
    print(f"Password:         {password}")
    print(f"API Key:          {api_key}")
    print("="*70)
    
    return smtp_server

def main():
    # Load environment variables from .env file
    load_dotenv()
    
    # Disable SSL warnings for GoPhish (self-signed certs)
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description='Create a new email address in Mailgun with auto-generated password'
    )
    parser.add_argument('-d', '--domain', required=True, help='Your Mailgun domain (e.g., mg.example.com)')
    parser.add_argument('-e', '--email', required=True, help='Email address to create (e.g., newuser@mg.example.com)')
    parser.add_argument('-r', '--region', choices=['us', 'eu'], default='eu', help='Mailgun API region: us or eu (default: us)')
    parser.add_argument('--password-length', type=int, default=20, help='Length of generated password (default: 20)')
    parser.add_argument('--add-to-gophish', action='store_true', help='Add/update credentials in GoPhish sending profile')
    parser.add_argument('--gophish-profile-id', type=int, help='GoPhish sending profile ID to update (if not provided, creates new profile)')
    parser.add_argument('--gophish-profile-name', help='Name for new GoPhish sending profile (default: email address)')
    
    args = parser.parse_args()
    
    # Set API base URL based on region
    api_base_urls = {
        'us': 'https://api.mailgun.net',
        'eu': 'https://api.eu.mailgun.net'
    }
    api_base_url = api_base_urls[args.region]
    
    # Get API key from environment
    api_key = os.getenv('MAILGUN_API_KEY')
    
    if not api_key:
        print("✗ Error: MAILGUN_API_KEY not found in .env file")
        print("  Please add MAILGUN_API_KEY=your-api-key to your .env file")
        return
    
    # If adding to GoPhish, check for required env vars
    if args.add_to_gophish:
        gophish_url = os.getenv('GOPHISH_URL')
        gophish_api_key = os.getenv('GOPHISH_API_KEY')
        
        if not gophish_url or not gophish_api_key:
            print("✗ Error: GoPhish credentials not found in .env file")
            print("  Please add GOPHISH_URL and GOPHISH_API_KEY to your .env file")
            print("  Example:")
            print("    GOPHISH_URL=https://your-gophish-instance.com")
            print("    GOPHISH_API_KEY=your-gophish-api-key")
            return
    
    # Generate random password
    password = generate_password(args.password_length)
    
    print(f"Creating email credentials for: {args.email}")
    print(f"Domain: {args.domain}")
    print(f"Region: {args.region.upper()} ({api_base_url})")
    print(f"Generated password length: {args.password_length} characters\n")
    
    # Create the credentials
    result = create_mailgun_credentials(
        domain=args.domain,
        email_address=args.email,
        password=password,
        api_key=api_key,
        api_base_url=api_base_url
    )
    
    if result:
        # Print all credentials
        smtp_server = print_credentials(args.email, password, api_key, args.domain, api_base_url, args.region)
        
        # Add to GoPhish if requested
        if args.add_to_gophish:
            print(f"\n{'='*70}")
            print("GOPHISH INTEGRATION")
            print(f"{'='*70}")
            
            if args.gophish_profile_id:
                # Update existing profile
                print(f"Updating GoPhish sending profile ID: {args.gophish_profile_id}")
                gophish_result = update_gophish_sending_profile(
                    gophish_url=gophish_url,
                    gophish_api_key=gophish_api_key,
                    profile_id=args.gophish_profile_id,
                    email=args.email,
                    password=password,
                    smtp_server=smtp_server
                )
            else:
                # Create new profile - check if name already exists
                profile_name = args.gophish_profile_name or args.email
                
                print(f"Checking if GoPhish profile '{profile_name}' already exists...")
                existing_profile = check_gophish_profile_exists(
                    gophish_url=gophish_url,
                    gophish_api_key=gophish_api_key,
                    profile_name=profile_name
                )
                
                if existing_profile:
                    print(f"\n✗ ERROR: GoPhish sending profile '{profile_name}' already exists!")
                    print(f"  Profile ID: {existing_profile.get('id')}")
                    print(f"  Profile Name: {existing_profile.get('name')}")
                    print(f"\nOptions:")
                    print(f"  1. Choose a different profile name with --gophish-profile-name 'New Name'")
                    print(f"  2. Update the existing profile with --gophish-profile-id {existing_profile.get('id')}")
                    print(f"{'='*70}")
                    return
                
                print(f"Creating new GoPhish sending profile: {profile_name}")
                gophish_result = create_gophish_sending_profile(
                    gophish_url=gophish_url,
                    gophish_api_key=gophish_api_key,
                    name=profile_name,
                    email=args.email,
                    password=password,
                    smtp_server=smtp_server
                )
            
            if gophish_result:
                print(f"✓ GoPhish sending profile configured successfully")
                print(f"  Profile ID: {gophish_result.get('id', 'N/A')}")
                print(f"  Profile Name: {gophish_result.get('name', 'N/A')}")
            print(f"{'='*70}")
    else:
        print("\n✗ Failed to create credentials")

if __name__ == '__main__':
    main()
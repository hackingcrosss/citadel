#!/usr/bin/env python3
"""
Website Generator + Docker Container Creator
Generates industry-specific websites and automatically adds them to docker-compose.yaml

Usage:
    python website_to_container.py --yaml docker-compose.yaml --container blog --industry "tech startup"
    python website_to_container.py --yaml docker-compose.yaml --container health --industry "healthcare" --api-key <key>
    python website_to_container.py --yaml docker-compose.yaml --container finance --industry "fintech" --no-start
    python website_to_container.py --yaml docker-compose.yaml --container portfolio --industry "design" --no-output
"""

from openai import AzureOpenAI
import json
import os
import argparse
import re
import sys
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
import yaml
from collections import OrderedDict


# Global flag for silent mode
SILENT_MODE = False


def sprint(*args, **kwargs):
    """Print wrapper that respects SILENT_MODE flag."""
    if not SILENT_MODE:
        print(*args, **kwargs)


def represent_ordereddict(dumper, data):
    """Custom representer for OrderedDict to maintain order in YAML output."""
    return dumper.represent_mapping('tag:yaml.org,2002:map', data.items())


class WebsiteGenerator:
    def __init__(self, api_key=None):
        """Initialize the website generator with Azure OpenAI API."""
        self.endpoint = "https://swedencentral.api.cognitive.microsoft.com/"
        self.deployment = "model-router"
        self.api_version = "2025-01-01-preview"
        self.client = AzureOpenAI(
            api_version=self.api_version,
            azure_endpoint=self.endpoint,
            api_key=api_key,
        )
    
    def generate_website_plan(self, industry):
        """Generate a comprehensive plan for the website."""
        sprint(f"[+] Planning website for {industry} industry...")
        
        planning_prompt = f"""You are a creative web designer creating a website for a business in the {industry} industry.

Generate a comprehensive website plan including:

1. **Brand Identity**
   - Business name (creative, memorable)
   - Tagline/slogan
   - Color palette (4-6 colors with hex codes)
   - Font recommendations (2-3 fonts from Google Fonts)
   - Overall aesthetic direction (be specific and creative)

2. **Content Strategy**
   - Hero section headline and subheadline
   - 3-4 key value propositions
   - About section content (2-3 paragraphs)
   - 4-6 services/features to highlight
   - Call-to-action text
   - Footer information

3. **Design Direction**
   - Choose a bold, distinctive aesthetic that fits the industry
   - Describe the visual style (modern minimal, brutalist, editorial, retro-futuristic, organic, luxury, etc.)
   - Key design elements to include
   - Animation/interaction ideas

Return your response as valid JSON with this structure:
{{
  "brand": {{
    "name": "string",
    "tagline": "string",
    "colors": {{"primary": "#hex", "secondary": "#hex", "accent": "#hex", "background": "#hex", "text": "#hex"}},
    "fonts": {{"display": "Font Name", "body": "Font Name"}},
    "aesthetic": "detailed description"
  }},
  "content": {{
    "hero": {{"headline": "string", "subheadline": "string"}},
    "valueProps": ["string", "string", "string"],
    "about": "multi-paragraph string",
    "services": [{{"title": "string", "description": "string"}}, ...],
    "cta": "string",
    "footer": {{"email": "string", "phone": "string", "address": "string"}}
  }},
  "design": {{
    "style": "string",
    "keyElements": ["string", "string"],
    "interactions": "string"
  }}
}}

Make this unique and tailored specifically to {industry}. Avoid generic, cookie-cutter designs."""

        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "user", "content": planning_prompt}],
            max_tokens=4000,
            temperature=0.7
        )
        
        # Extract JSON from response
        content = response.choices[0].message.content
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            plan = json.loads(json_match.group())
            return plan
        else:
            raise ValueError("Could not extract JSON from planning response")
    
    def generate_html(self, plan, industry):
        """Generate the complete HTML/CSS/JS website code."""
        sprint("[+] Generating website code...")
        
        code_prompt = f"""Create a complete, production-ready single-page website based on this plan:

{json.dumps(plan, indent=2)}

Industry: {industry}

Requirements:
1. Single HTML file with embedded CSS and JavaScript
2. Fully responsive (mobile-first)
3. Modern, semantic HTML5
4. High-quality aesthetic following the design direction
5. Smooth animations and micro-interactions
6. Professional typography and spacing
7. Functional contact form (frontend validation)
8. SEO-friendly meta tags
9. Accessibility features (ARIA labels, semantic markup)
10. Performance-optimized (efficient CSS, minimal dependencies)

Design principles from the plan:
- Aesthetic: {plan['design']['style']}
- Key elements: {', '.join(plan['design']['keyElements'])}
- Interactions: {plan['design']['interactions']}

Include:
- Navigation menu
- Hero section with the headline and CTA
- About section
- Services/Features section (grid or cards)
- Contact section with form
- Footer

Use Google Fonts for: {plan['brand']['fonts']['display']} and {plan['brand']['fonts']['body']}

Color palette:
{json.dumps(plan['brand']['colors'], indent=2)}

Make this production-grade, visually striking, and unique. Avoid generic AI aesthetics.
Use creative layouts, unexpected typography choices, engaging animations.

Return ONLY the complete HTML code, no explanations."""

        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "user", "content": code_prompt}],
            temperature=0.7
        )
        
        content = response.choices[0].message.content
        finish_reason = response.choices[0].finish_reason
        
        # Debug output
        sprint(f"[+] API Response - Length: {len(content) if content else 0} characters")
        sprint(f"[+] Finish reason: {finish_reason}")
        
        if finish_reason == "length":
            sprint("[!] WARNING: Response was truncated due to token limit!")
        
        if not content:
            sprint("[!] ERROR: API returned empty content!")
        
        return content
    
    def clean_html_code(self, html_text):
        """Extract and clean HTML code from response."""
        if not html_text:
            sprint("[!] Warning: Received empty HTML text")
            return ""
        
        sprint(f"[+] Raw response length: {len(html_text)} characters")
        
        # Remove markdown code blocks if present (handle multiple formats)
        html_text = re.sub(r'^```html\s*\n', '', html_text, flags=re.MULTILINE)
        html_text = re.sub(r'^```\s*\n', '', html_text, flags=re.MULTILINE)
        html_text = re.sub(r'\n```\s*$', '', html_text, flags=re.MULTILINE)
        html_text = re.sub(r'```html', '', html_text)
        html_text = re.sub(r'```', '', html_text)
        html_text = html_text.strip()
        
        # Validate we have actual HTML
        if not html_text:
            sprint("[!] ERROR: HTML is empty after cleaning markdown blocks")
            return ""
        
        if '<!DOCTYPE' not in html_text.upper() and '<HTML' not in html_text.upper():
            sprint("[!] WARNING: Content doesn't appear to be valid HTML")
            sprint(f"[+] First 200 characters after cleaning: {html_text[:200]}")
        
        sprint(f"[+] Cleaned HTML length: {len(html_text)} characters")
        return html_text


def add_nginx_container(yaml_file, container_name, grooming_dir):
    """
    Add a new nginx container to the docker-compose YAML file.
    Always overwrites the original YAML file.
    
    Args:
        yaml_file: Path to input YAML file
        container_name: Name for the new container
        grooming_dir: Path to the grooming directory (for verification)
    """
    # Register OrderedDict representer
    yaml.add_representer(OrderedDict, represent_ordereddict)
    
    sprint(f"\n[+] Updating docker-compose.yaml...")
    
    # Read the YAML file
    with open(yaml_file, 'r') as f:
        data = yaml.safe_load(f)
    
    # Check if services section exists
    if 'services' not in data:
        sprint("[!] Error: 'services' section not found in YAML file")
        sys.exit(1)
    
    # Create the service name
    service_name = f"nginx_{container_name}"
    
    # Check if service already exists
    if service_name in data['services']:
        sprint(f"[!] Warning: Service '{service_name}' already exists in the file")
        overwrite = input("Do you want to overwrite it? (y/n): ").lower()
        if overwrite != 'y':
            sprint("[!] Aborted.")
            return False
    
    # Create the new nginx container configuration
    new_container = OrderedDict([
        ('image', 'nginx:latest'),
        ('container_name', container_name),
        ('volumes', [f'./grooming/{container_name}:/usr/share/nginx/html:ro']),
        ('networks', ['npm_network'])
    ])
    
    # Add the new container to services
    data['services'][service_name] = new_container
    
    # Always overwrite the original YAML file
    with open(yaml_file, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, width=1000)
    
    sprint(f"[+] Successfully added '{service_name}' container to {yaml_file}")
    sprint(f"[+] Container details:")
    sprint(f"    Service name: {service_name}")
    sprint(f"    Container name: {container_name}")
    sprint(f"    Volume mapping: ./grooming/{container_name}:/usr/share/nginx/html:ro")
    
    return True


def start_docker_container(yaml_file, container_name):
    """
    Start the newly created Docker container using docker-compose.
    
    Args:
        yaml_file: Path to docker-compose.yaml
        container_name: Name of the container to start
    
    Returns:
        bool: True if successful, False otherwise
    """
    sprint(f"\n[+] Starting Docker container '{container_name}'...")
    
    # Get the directory of the yaml file to run docker-compose from there
    yaml_dir = Path(yaml_file).parent.resolve()
    yaml_filename = Path(yaml_file).name
    service_name = f"nginx_{container_name}"
    
    try:
        # Run docker-compose up -d for the specific container
        result = subprocess.run(
            ['docker-compose', '-f', yaml_filename, 'up', '-d', service_name],
            cwd=yaml_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            sprint(f"[+] Container '{container_name}' started successfully!")
            if result.stdout:
                sprint(f"    Output: {result.stdout.strip()}")
            return True
        else:
            sprint(f"[!] Failed to start container '{container_name}'")
            if result.stderr:
                sprint(f"    Error: {result.stderr.strip()}")
            return False
            
    except subprocess.TimeoutExpired:
        sprint(f"[!] Timeout: Container took too long to start")
        return False
    except FileNotFoundError:
        sprint(f"[!] Error: docker-compose command not found")
        sprint(f"    Make sure Docker and docker-compose are installed")
        return False
    except Exception as e:
        sprint(f"[!] Error starting container: {e}")
        return False


def generate_and_deploy_website(industry, yaml_file, container_name, api_key, temp_output_dir="generated_websites", no_start=False):
    """
    Main function to generate website and deploy to container.
    
    Args:
        industry: Industry type for website generation
        yaml_file: Path to docker-compose.yaml
        container_name: Name for the container
        api_key: Azure OpenAI API key
        temp_output_dir: Temporary directory for full website artifacts
        no_start: If True, skip starting the container
    """
    sprint(f"\n{'='*60}")
    sprint(f"[+] Website to Container Pipeline")
    sprint(f"[+] Industry: {industry}")
    sprint(f"[+] Container: {container_name}")
    sprint(f"[+] YAML: {yaml_file}")
    sprint(f"{'='*60}\n")
    
    # Step 1: Generate website
    generator = WebsiteGenerator(api_key=api_key)
    
    # Generate plan
    plan = generator.generate_website_plan(industry)
    sprint(f"[+] Plan created for: {plan['brand']['name']}")
    
    # Generate code
    html_code = generator.generate_html(plan, industry)
    
    if not html_code:
        raise ValueError("HTML generation returned empty content from API")
    
    html_code = generator.clean_html_code(html_code)
    
    if not html_code:
        raise ValueError("HTML code is empty after cleaning - check API response format")
    
    sprint(f"[+] Website code generated ({len(html_code)} characters)")
    
    # Step 2: Create grooming directory
    yaml_dir = Path(yaml_file).parent.resolve()
    grooming_dir = yaml_dir / 'grooming' / container_name
    
    sprint(f"\n[+] Creating container directory: {grooming_dir}")
    try:
        grooming_dir.mkdir(parents=True, exist_ok=True)
        sprint(f"[+] Directory created successfully")
    except Exception as e:
        sprint(f"[!] Error creating directory {grooming_dir}: {e}")
        sys.exit(1)
    
    # Step 3: Save index.html to grooming directory
    index_file = grooming_dir / "index.html"
    sprint(f"[+] Saving index.html to: {index_file}")
    
    with open(index_file, 'w', encoding='utf-8') as f:
        f.write(html_code)
    
    if index_file.exists():
        file_size = index_file.stat().st_size
        sprint(f"[+] index.html saved successfully ({file_size} bytes)")
    else:
        sprint("[!] ERROR: index.html was not created!")
        sys.exit(1)
    
    # Step 4: Save full website artifacts to temp directory (optional reference)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    site_name = plan['brand']['name'].lower().replace(' ', '_')
    temp_site_dir = Path(temp_output_dir) / f"{site_name}_{timestamp}"
    temp_site_dir.mkdir(parents=True, exist_ok=True)
    
    # Save plan as JSON
    plan_file = temp_site_dir / "plan.json"
    with open(plan_file, 'w', encoding='utf-8') as f:
        json.dump(plan, f, indent=2)
    
    # Save copy of index.html
    temp_index = temp_site_dir / "index.html"
    shutil.copy(str(index_file), str(temp_index))
    
    # Create README
    readme_content = f"""# {plan['brand']['name']}

**Industry:** {industry}
**Container:** {container_name}
**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Deployment
The website has been deployed to the Docker container:
- **Container name:** {container_name}
- **Service name:** nginx_{container_name}
- **Web root:** ./grooming/{container_name}/

## Files
- `index.html` - Website (also deployed to container)
- `plan.json` - Website plan and content

## Brand Identity
- **Name:** {plan['brand']['name']}
- **Tagline:** {plan['brand']['tagline']}
- **Aesthetic:** {plan['design']['style']}

## Access
After starting the container, access the website through your nginx proxy manager.
"""
    
    readme_file = temp_site_dir / "README.md"
    with open(readme_file, 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    sprint(f"[+] Full website artifacts saved to: {temp_site_dir}")
    
    # Step 5: Update docker-compose.yaml
    success = add_nginx_container(yaml_file, container_name, grooming_dir)
    
    if not success:
        sprint("[!] Failed to update docker-compose.yaml")
        sys.exit(1)
    
    # Step 6: Start the container (unless --no-start is specified)
    container_started = False
    if not no_start:
        container_started = start_docker_container(yaml_file, container_name)
    else:
        sprint(f"\n[+] Skipping container start (--no-start specified)")
    
    # Final summary
    sprint(f"\n{'='*60}")
    sprint(f"[+] SUCCESS! Website deployed to container")
    sprint(f"{'='*60}")
    sprint(f"\nDeployment Summary:")
    sprint(f"  ✓ Website generated: {plan['brand']['name']}")
    sprint(f"  ✓ Index saved to: {index_file}")
    sprint(f"  ✓ Container added: nginx_{container_name}")
    sprint(f"  ✓ YAML updated: {yaml_file}")
    sprint(f"  ✓ Artifacts saved: {temp_site_dir}")
    if container_started:
        sprint(f"  ✓ Container started: {container_name} is now running!")
    elif not no_start:
        sprint(f"  [!] Container not started: Start manually with:")
        sprint(f"    docker-compose -f {yaml_file} up -d {container_name}")
    else:
        sprint(f"  [!] Container not started (--no-start)")
    sprint(f"\nNext steps:")
    if container_started:
        sprint(f"  1. Verify container is running: docker ps | grep {container_name}")
        sprint(f"  2. Configure nginx proxy manager to route to {container_name}")
        sprint(f"  3. Test the website through your proxy")
    else:
        sprint(f"  1. Start the container: docker-compose -f {yaml_file} up -d {container_name}")
        sprint(f"  2. Configure nginx proxy manager to route to {container_name}")
    sprint(f"{'='*60}\n")
    
    return grooming_dir, temp_site_dir


def main():
    global SILENT_MODE
    
    parser = argparse.ArgumentParser(
        description="Generate websites and deploy to Docker containers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --yaml docker-compose.yaml --container blog --industry "tech startup"
  %(prog)s --yaml docker-compose.yaml --container health --industry "healthcare" --api-key <key>
  %(prog)s --yaml docker-compose.yaml --container finance --industry "fintech" --output-dir ./archives
  %(prog)s --yaml docker-compose.yaml --container portfolio --industry "design" --no-start
  %(prog)s --yaml docker-compose.yaml --container silent --industry "tech" --no-output
        """
    )
    
    parser.add_argument(
        '--yaml',
        type=str,
        required=True,
        help='Path to docker-compose.yaml file'
    )
    
    parser.add_argument(
        '--container',
        type=str,
        required=True,
        help='Name for the container (without nginx_ prefix)'
    )
    
    parser.add_argument(
        '--industry',
        type=str,
        required=True,
        help='Industry/field for the website (e.g., "tech", "health", "finance")'
    )
    
    parser.add_argument(
        '--api-key',
        type=str,
        default=None,
        help='Azure OpenAI API key (or set AZURE_OPENAI_API_KEY env variable)'
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        default='generated_websites',
        help='Directory for website artifacts/archives (default: generated_websites)'
    )
    
    parser.add_argument(
        '--no-start',
        action='store_true',
        help='Skip starting the container automatically'
    )
    
    parser.add_argument(
        '--no-output',
        action='store_true',
        help='Suppress all stdout messages (silent mode)'
    )
    
    args = parser.parse_args()
    
    # Set silent mode if --no-output is specified
    SILENT_MODE = args.no_output
    
    # Validate YAML file exists
    if not Path(args.yaml).exists():
        sprint(f"[!] Error: YAML file '{args.yaml}' not found")
        return 1
    
    # Get API key
    api_key = args.api_key or os.environ.get('AZURE_OPENAI_API_KEY')
    if not api_key:
        sprint("[!] Error: Azure OpenAI API key required.")
        sprint("Set AZURE_OPENAI_API_KEY environment variable or use --api-key")
        return 1
    
    # Generate and deploy
    try:
        grooming_dir, temp_dir = generate_and_deploy_website(
            industry=args.industry,
            yaml_file=args.yaml,
            container_name=args.container,
            api_key=api_key,
            temp_output_dir=args.output_dir,
            no_start=args.no_start
        )
        return 0
    except Exception as e:
        sprint(f"\n[!] Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
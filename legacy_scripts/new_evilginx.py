import json
import argparse

# -------------------------
# Hardcoded JSON template
# -------------------------
CONFIG_TEMPLATE="config.json.template"


def generate_json_from_template(
    domain: str,
    url: str,
    phishlet: str,
    path = None
) -> dict:
    """
    Load a JSON template, inject provided values, and return the new JSON.
    """
    with open(CONFIG_TEMPLATE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Copy provided values into the template
    data["general"]["domain"] = domain
    data["general"]["unauth_url"] = url
    data["phishlets"][phishlet] = [{
        "hostname": domain,
        "unauth_url": "",
        "enabled": True,
        "visible": True

    }]
    data["lures"] = [{
        "hostname": "",
        "id": "",
        "info": "",
        "og_desc": "",
        "og_image": "",
        "og_title": "",
        "og_url": "",
        "path": "" if not path else path,
        "paused": 0,
        "phishlet": phishlet,
        "redirect_url": "",
        "redirector": "",
        "ua_filter": ""
    }]

    return data


def main():
    parser = argparse.ArgumentParser(description="Generate JSON from a hardcoded template")
    parser.add_argument("-d", "--domain", required=True, help="Domain name")
    parser.add_argument("-u", "--unauth_url", default="https://google.com", help="URL to send unauth visitors to.")
    parser.add_argument("-p", "--phishlet", required=True, help="Input phishlet to configure the lure and domain")
    parser.add_argument("--path", default=None, help="Input phishlet to configure the lure and domain")

    args = parser.parse_args()

    result = generate_json_from_template(
        domain=args.domain,
        url=args.unauth_url,
        phishlet=args.phishlet,
        path=args.path
    )

    output_file = f"{args.domain}.config.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"✅ JSON generated: {output_file}")


if __name__ == "__main__":
    main()

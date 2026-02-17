"""
Project 3: Verify Railway Deployment

Checks that your Railway deployment is healthy and accessible.

Usage:
    python verify_deployment.py https://your-app.up.railway.app
"""

import sys
import urllib.request
import json


def check_endpoint(base_url: str, path: str, description: str) -> bool:
    """Check if an endpoint is reachable and returns valid JSON."""
    url = f"{base_url.rstrip('/')}{path}"
    print(f"\n{'='*50}")
    print(f"Checking: {description}")
    print(f"URL:      {url}")
    print(f"{'='*50}")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Railway-Verify/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            print(f"Status:   {response.status}")
            print(f"Response: {json.dumps(data, indent=2)}")
            print(f"Result:   PASS")
            return True

    except Exception as e:
        print(f"Result:   FAIL")
        print(f"Error:    {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python verify_deployment.py <railway-url>")
        print("Example: python verify_deployment.py https://your-app.up.railway.app")
        sys.exit(1)

    base_url = sys.argv[1]
    print(f"Verifying Railway deployment at: {base_url}")

    results = {}

    results["Health Endpoint"] = check_endpoint(base_url, "/health", "Health check endpoint")
    results["Root Endpoint"] = check_endpoint(base_url, "/", "Root endpoint")

    # Check logs endpoint (may return 503 if no DB, that's OK)
    url = f"{base_url.rstrip('/')}/logs"
    print(f"\n{'='*50}")
    print(f"Checking: Logs endpoint")
    print(f"URL:      {url}")
    print(f"{'='*50}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Railway-Verify/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            print(f"Status:   {response.status}")
            print(f"Result:   PASS (database connected)")
            results["Logs Endpoint"] = True
    except urllib.error.HTTPError as e:
        if e.code == 503:
            print(f"Status:   503")
            print(f"Result:   WARN (database not configured, but endpoint exists)")
            results["Logs Endpoint"] = True
        else:
            print(f"Result:   FAIL ({e})")
            results["Logs Endpoint"] = False
    except Exception as e:
        print(f"Result:   FAIL ({e})")
        results["Logs Endpoint"] = False

    # Summary
    print(f"\n{'='*50}")
    print("VERIFICATION SUMMARY")
    print(f"{'='*50}")

    all_passed = True
    for check, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {check}")
        if not passed:
            all_passed = False

    if all_passed:
        print(f"\nDeployment is healthy!")
        print(f"\nNext: python update_plivo.py {base_url}")
    else:
        print(f"\nSome checks failed. Check: railway logs")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

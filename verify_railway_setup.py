"""
Project 1: Verify Railway CLI Setup

Checks that Railway CLI is installed and you're logged in.

Steps before running this:
    1. Sign up at https://railway.app (use GitHub)
    2. Install CLI: npm install -g @railway/cli
    3. Login: railway login
    4. Run: python verify_railway_setup.py
"""

import subprocess
import sys


def run_command(cmd: list[str], description: str) -> tuple[bool, str]:
    """Run a command and return (success, output)."""
    print(f"\n{'='*50}")
    print(f"Checking: {description}")
    print(f"Command:  {' '.join(cmd)}")
    print(f"{'='*50}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        output = result.stdout.strip() or result.stderr.strip()
        success = result.returncode == 0
        print(f"Status:   {'PASS' if success else 'FAIL'}")
        print(f"Output:   {output}")
        return success, output
    except FileNotFoundError:
        print(f"Status:   FAIL")
        print(f"Output:   Command not found - is Railway CLI installed?")
        return False, "Command not found"
    except subprocess.TimeoutExpired:
        print(f"Status:   FAIL")
        print(f"Output:   Command timed out")
        return False, "Timeout"


def main():
    print("Railway CLI Setup Verification")
    print("=" * 50)

    results = {}

    # Check 1: Railway CLI installed
    ok, output = run_command(["railway", "version"], "Railway CLI installed")
    results["CLI Installed"] = ok

    # Check 2: Logged in
    ok, output = run_command(["railway", "whoami"], "Railway CLI logged in")
    results["Logged In"] = ok

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
        print("\nAll checks passed! Railway CLI is ready.")
    else:
        print("\nSome checks failed. Fix the issues above:")
        if not results.get("CLI Installed"):
            print("  - Install Railway CLI: npm install -g @railway/cli")
        if not results.get("Logged In"):
            print("  - Login to Railway: railway login")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

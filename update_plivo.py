"""
Project 4: Update Plivo Phone Number to Use Railway URL

Programmatically updates your Plivo phone number's Answer URL
to point to your Railway deployment instead of ngrok.

Usage:
    python update_plivo.py https://your-app.up.railway.app
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()


def update_plivo_number(railway_url: str):
    """Update Plivo phone number Answer URL to Railway."""
    try:
        import plivo
    except ImportError:
        print("ERROR: plivo package not installed.")
        print("Run: pip install plivo")
        sys.exit(1)

    auth_id = os.getenv("PLIVO_AUTH_ID")
    auth_token = os.getenv("PLIVO_AUTH_TOKEN")
    phone_number = os.getenv("PLIVO_PHONE_NUMBER")

    if not all([auth_id, auth_token]):
        print("ERROR: PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN must be set.")
        sys.exit(1)

    client = plivo.RestClient(auth_id, auth_token)
    answer_url = f"{railway_url.rstrip('/')}/answer"

    if phone_number:
        print(f"Updating Plivo number {phone_number}...")
        print(f"  Answer URL: {answer_url}")
        print(f"  Method: POST")

        try:
            response = client.numbers.update(
                phone_number,
                answer_url=answer_url,
                answer_method="POST",
            )
            print(f"\nSUCCESS! Number updated.")
            print(f"  Number: {phone_number}")
            print(f"  Answer URL: {answer_url}")
        except Exception as e:
            print(f"\nFAILED to update: {e}")
            print("\nUpdate manually:")
            print(f"  1. Go to https://console.plivo.com/phone-numbers/")
            print(f"  2. Click on your number: {phone_number}")
            print(f"  3. Set Answer URL to: {answer_url}")
            print(f"  4. Set Method to: POST")
            print(f"  5. Save")
    else:
        print("PLIVO_PHONE_NUMBER not set. Listing your numbers...")
        try:
            response = client.numbers.list(offset=0, limit=20)
            numbers = response["objects"] if isinstance(response, dict) else response.objects
            print(f"\nYour Plivo numbers:")
            for num in numbers:
                number = num.get("number", num.number if hasattr(num, "number") else "?")
                print(f"  - {number}")
            print(f"\nSet PLIVO_PHONE_NUMBER in .env, then run again.")
        except Exception as e:
            print(f"\nCouldn't list numbers: {e}")
            print(f"\nUpdate manually in the Plivo console:")
            print(f"  Answer URL: {answer_url}")
            print(f"  Method: POST")


def main():
    if len(sys.argv) < 2:
        print("Usage: python update_plivo.py <railway-url>")
        print("Example: python update_plivo.py https://your-app.up.railway.app")
        sys.exit(1)

    railway_url = sys.argv[1]

    print("=" * 50)
    print("  Update Plivo to Use Railway URL")
    print("=" * 50)
    print(f"\nRailway URL: {railway_url}")
    print(f"Answer URL:  {railway_url.rstrip('/')}/answer")

    update_plivo_number(railway_url)

    print(f"\n{'='*50}")
    print("NEXT STEPS")
    print(f"{'='*50}")
    print("  1. Call your Plivo number to test")
    print("  2. Watch logs: railway logs --tail")
    print("  3. Verify: python verify_plivo.py")


if __name__ == "__main__":
    main()

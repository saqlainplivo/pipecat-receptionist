"""
Project 4: Verify Plivo Configuration

Checks that your Plivo number is pointing to the Railway URL.

Usage:
    python verify_plivo.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main():
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

    print("=" * 50)
    print("  Plivo Configuration Verification")
    print("=" * 50)

    try:
        response = client.numbers.list(offset=0, limit=20)
        numbers = response["objects"] if isinstance(response, dict) else response.objects

        print(f"\nFound {len(numbers)} number(s):\n")

        for num in numbers:
            number = getattr(num, "number", num.get("number", "?"))
            answer_url = getattr(num, "answer_url", num.get("answer_url", "Not set"))

            is_railway = "railway" in str(answer_url).lower() or ".up.railway.app" in str(answer_url)
            is_ngrok = "ngrok" in str(answer_url).lower()

            status = "RAILWAY" if is_railway else ("NGROK (update needed!)" if is_ngrok else "OTHER")
            marker = ">>>" if number == phone_number else "   "

            print(f"  {marker} {number}")
            print(f"       Answer URL: {answer_url}")
            print(f"       Status:     {status}")
            print()

        print("=" * 50)
        print("CHECKLIST")
        print("=" * 50)
        print("  [ ] Answer URL points to Railway (not ngrok)")
        print("  [ ] Method is set to POST")
        print("  [ ] Test call connects successfully")
        print("  [ ] AI receptionist responds")
        print("  [ ] Logs visible with: railway logs --tail")

    except Exception as e:
        print(f"\nError fetching numbers: {e}")
        print("\nVerify manually at: https://console.plivo.com/phone-numbers/")


if __name__ == "__main__":
    main()

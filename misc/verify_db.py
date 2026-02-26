"""
Project 5: Verify Database Logging

Connects to Vercel Postgres and checks that call logs are being saved
with all required fields: caller_number, transcript, detected_intent, duration.

Usage:
    python verify_db.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main():
    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not installed.")
        print("Run: pip install psycopg2-binary")
        sys.exit(1)

    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        print("ERROR: POSTGRES_URL not set in environment.")
        sys.exit(1)

    print("=" * 60)
    print("  Vercel Postgres - Call Log Verification")
    print("=" * 60)

    try:
        conn = psycopg2.connect(postgres_url)
        print("\nDatabase connection: OK")
    except Exception as e:
        print(f"\nDatabase connection: FAILED")
        print(f"Error: {e}")
        sys.exit(1)

    try:
        cur = conn.cursor()

        # Check both tables (Pipecat and LiveKit)
        tables = ["receptionist_call_logs", "livekit_receptionist_call_logs"]

        for table_name in tables:
            print(f"\n{'='*60}")
            print(f"  Table: {table_name}")
            print(f"{'='*60}")

            # Check if table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = %s
                )
            """, (table_name,))
            exists = cur.fetchone()[0]

            if not exists:
                print(f"  Table does not exist (not yet created)")
                continue

            # Get total count
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            total = cur.fetchone()[0]
            print(f"  Total call logs: {total}")

            if total == 0:
                print("  No calls logged yet. Make some test calls!")
                continue

            # Get recent logs
            cur.execute(f"""
                SELECT id, caller_number, transcript, detected_intent, duration, created_at
                FROM {table_name}
                ORDER BY created_at DESC
                LIMIT 5
            """)
            rows = cur.fetchall()

            print(f"\n  Recent calls (last {len(rows)}):")
            print(f"  {'-'*56}")

            all_valid = True
            for row in rows:
                log_id, caller, transcript, intent, duration, created_at = row

                has_caller = bool(caller and caller != "unknown")
                has_transcript = bool(transcript and len(transcript) > 0)
                has_intent = bool(intent and intent != "unknown")
                has_duration = duration is not None and duration > 0

                print(f"\n  Call #{log_id} ({created_at})")
                print(f"    Caller:     {caller}")
                print(f"    Intent:     {intent}")
                print(f"    Duration:   {duration}s")
                print(f"    Transcript: {transcript[:100]}{'...' if transcript and len(transcript) > 100 else ''}")
                print(f"    Checks:")
                print(f"      [{'x' if has_caller else ' '}] Caller number recorded")
                print(f"      [{'x' if has_transcript else ' '}] Transcript saved")
                print(f"      [{'x' if has_intent else ' '}] Intent detected")
                print(f"      [{'x' if has_duration else ' '}] Duration recorded")

                if not all([has_caller, has_transcript, has_intent, has_duration]):
                    all_valid = False

            print(f"\n  {'='*56}")
            if all_valid:
                print(f"  All recent calls have complete data!")
            else:
                print(f"  Some calls have incomplete data. Normal for short/dropped calls.")

        cur.close()

    except Exception as e:
        print(f"\nError querying database: {e}")
        sys.exit(1)
    finally:
        conn.close()

    print(f"\n{'='*60}")
    print("VERIFICATION CHECKLIST")
    print(f"{'='*60}")
    print("  [ ] Calls logged to Vercel Postgres")
    print("  [ ] Transcript saved correctly")
    print("  [ ] Intents detected correctly")
    print("  [ ] Duration recorded")
    print(f"\nAlso check: Vercel Dashboard -> Storage -> Postgres -> Data tab")


if __name__ == "__main__":
    main()

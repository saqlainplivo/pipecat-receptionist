"""
Database module for logging LiveKit receptionist calls to Vercel/Neon Postgres.
"""

import os
import psycopg2
from loguru import logger

def get_connection():
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        logger.warning("POSTGRES_URL not set - call logging disabled")
        return None
    return psycopg2.connect(postgres_url)

def init_db():
    conn = get_connection()
    if not conn: return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS livekit_receptionist_call_logs (
                id SERIAL PRIMARY KEY,
                caller_number VARCHAR(50) NOT NULL,
                transcript TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                detected_intent VARCHAR(100) DEFAULT 'unknown',
                duration INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"Database init error: {e}")
    finally:
        conn.close()

def log_call(caller_number: str, transcript: str, detected_intent: str, duration: int, summary: str = ""):
    conn = get_connection()
    if not conn: return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO livekit_receptionist_call_logs
                (caller_number, transcript, detected_intent, duration, summary)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (caller_number, transcript, detected_intent, duration, summary),
        )
        conn.commit()
        cur.close()
        logger.info(f"Call logged: caller={caller_number}, intent={detected_intent}")
    except Exception as e:
        logger.error(f"Failed to log call: {e}")
    finally:
        conn.close()

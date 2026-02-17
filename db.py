"""
Database module for logging calls to Vercel Postgres.

Stores: caller_number, transcript, detected_intent, duration, timestamp
"""

import os

import psycopg2
from loguru import logger


def get_connection():
    """Get a connection to Vercel Postgres."""
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        logger.warning("POSTGRES_URL not set - call logging disabled")
        return None
    return psycopg2.connect(postgres_url)


def init_db():
    """Create the call_logs table if it doesn't exist."""
    conn = get_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS receptionist_call_logs (
                id SERIAL PRIMARY KEY,
                caller_number VARCHAR(20) NOT NULL,
                transcript TEXT DEFAULT '',
                detected_intent VARCHAR(100) DEFAULT 'unknown',
                duration INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        logger.info("Database initialized - receptionist_call_logs table ready")
    except Exception as e:
        logger.error(f"Database init error: {e}")
    finally:
        conn.close()


def log_call(caller_number: str, transcript: str, detected_intent: str, duration: int):
    """Log a completed call to the database."""
    conn = get_connection()
    if not conn:
        logger.warning(f"Skipping DB log (no connection): {caller_number}, intent={detected_intent}")
        return

    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO receptionist_call_logs
                (caller_number, transcript, detected_intent, duration)
            VALUES (%s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (caller_number, transcript, detected_intent, duration),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        logger.info(f"Call logged: id={row[0]}, caller={caller_number}, intent={detected_intent}")
    except Exception as e:
        logger.error(f"Failed to log call: {e}")
    finally:
        conn.close()

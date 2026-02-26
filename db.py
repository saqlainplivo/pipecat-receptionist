"""
Database module for logging calls and latency metrics to Vercel Postgres.

Tables:
  receptionist_call_logs   — per-call summary (transcript, intent, duration, latency)
  call_latency_metrics     — per-turn latency breakdown (T0→T1, T1→T2, T0→T2)
"""

from __future__ import annotations

import json
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
    """Create tables if they don't exist."""
    conn = get_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        # Call logs table (add latency_json column if missing)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS receptionist_call_logs (
                id SERIAL PRIMARY KEY,
                caller_number VARCHAR(50) NOT NULL,
                transcript TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                detected_intent VARCHAR(100) DEFAULT 'unknown',
                duration INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Add columns if they don't exist (safe migrations)
        cur.execute("""
            ALTER TABLE receptionist_call_logs
            ADD COLUMN IF NOT EXISTS summary TEXT DEFAULT ''
        """)
        cur.execute("""
            ALTER TABLE receptionist_call_logs
            ADD COLUMN IF NOT EXISTS latency_json TEXT DEFAULT NULL
        """)

        # Per-turn latency metrics table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS call_latency_metrics (
                id SERIAL PRIMARY KEY,
                call_log_id INTEGER REFERENCES receptionist_call_logs(id),
                turn_number INTEGER NOT NULL,
                t0_t1_ms INTEGER,
                t1_t2_ms INTEGER,
                t0_t2_ms INTEGER NOT NULL,
                target_met BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        logger.info("Database initialized - receptionist_call_logs + call_latency_metrics ready")
    except Exception as e:
        logger.error(f"Database init error: {e}")
    finally:
        conn.close()


def log_call(
    caller_number: str,
    transcript: str,
    detected_intent: str,
    duration: int,
    summary: str = "",
    latency_data: list[dict] | None = None,
):
    """Log a completed call and its per-turn latency metrics to the database."""
    conn = get_connection()
    if not conn:
        logger.warning(f"Skipping DB log (no connection): {caller_number}, intent={detected_intent}")
        return

    try:
        cur = conn.cursor()
        latency_json = json.dumps(latency_data) if latency_data else None
        cur.execute(
            """
            INSERT INTO receptionist_call_logs
                (caller_number, transcript, detected_intent, duration, summary, latency_json)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (caller_number, transcript, detected_intent, duration, summary, latency_json),
        )
        row = cur.fetchone()
        call_log_id = row[0]
        conn.commit()
        logger.info(f"Call logged: id={call_log_id}, caller={caller_number}, intent={detected_intent}")

        # Insert per-turn latency rows
        if latency_data:
            for entry in latency_data:
                cur.execute(
                    """
                    INSERT INTO call_latency_metrics
                        (call_log_id, turn_number, t0_t1_ms, t1_t2_ms, t0_t2_ms, target_met)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        call_log_id,
                        entry.get("turn"),
                        entry.get("t0_t1_ms"),
                        entry.get("t1_t2_ms"),
                        entry.get("t0_t2_ms", 0),
                        entry.get("t0_t2_ms", 9999) < 1500,
                    ),
                )
            conn.commit()
            logger.info(f"Latency metrics logged: {len(latency_data)} turns for call {call_log_id}")

        cur.close()
    except Exception as e:
        logger.error(f"Failed to log call: {e}")
    finally:
        conn.close()

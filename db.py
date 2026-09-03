import os
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
    
load_dotenv()
DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db():
    """Ανοίγει σύνδεση με τη PostgreSQL βάση."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row
    )


def init_db():
    """Δημιουργεί τους πίνακες αν δεν υπάρχουν ήδη."""

    conn = get_db()

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                shares DOUBLE PRECISION NOT NULL,
                buy_price DOUBLE PRECISION NOT NULL,
                currency TEXT NOT NULL DEFAULT 'EUR',
                buy_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )

        conn.commit()

    finally:
        conn.close()
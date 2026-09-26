"""Run backend tests in a disposable PostgreSQL database, never the app DB.

Usage: .venv/bin/python backend/scripts/test_isolated.py [pytest arguments]
Uses the configured server credentials to create/drop only a generated rv_test DB.
"""
import os
from pathlib import Path
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import settings


def main() -> int:
    name = "soulmate_rv_test_" + uuid.uuid4().hex
    base = make_url(settings.database_url).set(drivername="postgresql")
    admin_url = base.set(database="postgres").render_as_string(hide_password=False)
    test_url = base.set(database=name).render_as_string(hide_password=False)
    env = dict(os.environ, DATABASE_URL=test_url, DEBUG="false", ENVIRONMENT="test",
               PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "backend"))
    # Never allow accidental real provider calls from an incompletely mocked test.
    env.update(PAYPAL_CLIENT_ID="isolated-test", PAYPAL_CLIENT_SECRET="isolated-test",
               PAYPAL_WEBHOOK_ID="WH-ISOLATED-TEST")
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            def run(*args):
                subprocess.run([sys.executable, *args], cwd=ROOT, env=env, check=True)
            # Exercise the published-revision upgrade as well as reverse compatibility.
            run("-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "0003_add_failed_payments")
            session_id, sub_id = uuid.uuid4(), uuid.uuid4()
            legacy_session_id = uuid.uuid4()
            checkpoint = datetime(2026, 9, 25, tzinfo=timezone.utc)
            with psycopg.connect(test_url) as db:
                db.execute("""INSERT INTO soulmate_sessions
                    (id, public_id, quiz_version, status, current_step)
                    VALUES (%s, %s, 'soulmate-quiz-v1', 'EMAIL_CAPTURED', 'subscribe')""",
                    (session_id, str(session_id)))
                # Legacy post-payment status written by the pre-M7 writer (0005 normalizes it).
                db.execute("""INSERT INTO soulmate_sessions
                    (id, public_id, quiz_version, status, current_step)
                    VALUES (%s, %s, 'soulmate-quiz-v1', 'paid', 'result')""",
                    (legacy_session_id, str(legacy_session_id)))
                db.execute("""INSERT INTO subscriptions
                    (id, session_id, provider_subscription_id, provider_plan_id, provider_status,
                     currency, regular_price, cancelled_at, billing_issue_detected_at)
                    VALUES (%s, %s, 'I-MIGRATION-ONLY', 'P-MIGRATION', 'CANCELLED',
                            'USD', 29, %s, %s)""", (sub_id, session_id, checkpoint, checkpoint))
            run("-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head")
            with psycopg.connect(test_url) as db:
                assert db.execute("""SELECT provider_status_updated_at, billing_updated_at
                    FROM subscriptions WHERE id=%s""", (sub_id,)).fetchone() == (checkpoint, checkpoint)
                assert db.execute("SELECT status FROM soulmate_sessions WHERE id=%s",
                                  (legacy_session_id,)).fetchone()[0] == "SUBSCRIBED"
            run("-m", "alembic", "-c", "backend/alembic.ini", "downgrade", "0003_add_failed_payments")
            with psycopg.connect(test_url) as db:
                assert db.execute("SELECT cancelled_at FROM subscriptions WHERE id=%s", (sub_id,)).fetchone() == (checkpoint,)
            run("-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head")
            with psycopg.connect(test_url) as db:
                assert db.execute("""SELECT provider_status_updated_at, billing_updated_at
                    FROM subscriptions WHERE id=%s""", (sub_id,)).fetchone() == (checkpoint, checkpoint)
                assert db.execute("SELECT status FROM soulmate_sessions WHERE id=%s",
                                  (legacy_session_id,)).fetchone()[0] == "SUBSCRIBED"
                db.execute("DELETE FROM subscriptions WHERE id=%s", (sub_id,))
                db.execute("DELETE FROM soulmate_sessions WHERE id=%s", (session_id,))
                db.execute("DELETE FROM soulmate_sessions WHERE id=%s", (legacy_session_id,))
            print("Migration upgrade/downgrade/re-upgrade with preserved data: PASS", flush=True)
            run("-m", "app.quiz.seed")
            run("-m", "pytest", "-p", "no:cacheprovider", *(sys.argv[1:] or ["backend/tests", "-q"]))
            return 0
        except subprocess.CalledProcessError as exc:
            return exc.returncode
        finally:
            # Only the DB created above is eligible for cleanup.
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            print("Disposable PostgreSQL database removed.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

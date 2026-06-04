import asyncio
import logging
import time

from sqlalchemy.exc import OperationalError

from database.db import get_session
from database.models import User, ActivityLog


LOCK_RETRY_ATTEMPTS = 3
LOCK_RETRY_DELAY_SECONDS = 0.25


def _is_sqlite_locked(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


def _log_task_result(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logging.debug("Analytics background task cancelled")
    except Exception as exc:
        logging.warning("Analytics background task failed: %s", type(exc).__name__)


def _schedule_log_task(func, *args) -> None:
    try:
        task = asyncio.create_task(asyncio.to_thread(func, *args))
        task.add_done_callback(_log_task_result)
    except RuntimeError:
        logging.warning("Skipped analytics event because no event loop was running")


def _sync_log_event(user_id: int, platform: str, event_type: str, event_name: str = None):
    """Best-effort analytics write; user-facing commands must not fail on log locks."""
    for attempt in range(1, LOCK_RETRY_ATTEMPTS + 1):
        session = get_session()
        try:
            log = ActivityLog(
                user_id=user_id,
                bot_id='gamebot',
                platform=platform,
                event_type=event_type,
                event_name=event_name
            )
            session.add(log)
            session.commit()
            return
        except OperationalError as exc:
            session.rollback()
            if _is_sqlite_locked(exc) and attempt < LOCK_RETRY_ATTEMPTS:
                time.sleep(LOCK_RETRY_DELAY_SECONDS * attempt)
                continue
            if _is_sqlite_locked(exc):
                logging.warning("Skipped analytics event after SQLite lock retries: %s", event_type)
            else:
                logging.warning("Failed to log analytics event %s: %s", event_type, type(exc).__name__)
            return
        except Exception as exc:
            session.rollback()
            logging.warning("Failed to log analytics event %s: %s", event_type, type(exc).__name__)
            return
        finally:
            session.close()


def log_event(user_id: int, platform: str, event_type: str, event_name: str = None):
    """Logs an activity event in the background without blocking command handlers."""
    _schedule_log_task(_sync_log_event, user_id, platform, event_type, event_name)


def _lookup_user_id(**filters):
    for attempt in range(1, LOCK_RETRY_ATTEMPTS + 1):
        session = get_session()
        try:
            user = session.query(User).filter_by(**filters).first()
            return user.id if user else None
        except OperationalError as exc:
            session.rollback()
            if _is_sqlite_locked(exc) and attempt < LOCK_RETRY_ATTEMPTS:
                time.sleep(LOCK_RETRY_DELAY_SECONDS * attempt)
                continue
            if _is_sqlite_locked(exc):
                logging.warning("Skipped analytics user lookup after SQLite lock retries")
            else:
                logging.warning("Failed analytics user lookup: %s", type(exc).__name__)
            return None
        except Exception as exc:
            session.rollback()
            logging.warning("Failed analytics user lookup: %s", type(exc).__name__)
            return None
        finally:
            session.close()


def _sync_log_tg_event(telegram_id: int, event_type: str, event_name: str = None):
    user_id = _lookup_user_id(telegram_id=telegram_id)
    if user_id:
        _sync_log_event(user_id, 'telegram', event_type, event_name)


def log_tg_event(telegram_id: int, event_type: str, event_name: str = None):
    """Helper to log Telegram events using telegram_id asynchronously."""
    _schedule_log_task(_sync_log_tg_event, telegram_id, event_type, event_name)


def _sync_log_tt_event(tiktok_id: str, event_type: str, event_name: str = None):
    user_id = _lookup_user_id(tiktok_id=tiktok_id)
    if user_id:
        _sync_log_event(user_id, 'tiktok', event_type, event_name)


def log_tt_event(tiktok_id: str, event_type: str, event_name: str = None):
    """Helper to log TikTok events using tiktok_id asynchronously."""
    _schedule_log_task(_sync_log_tt_event, tiktok_id, event_type, event_name)

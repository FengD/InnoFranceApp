from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


@dataclass
class UserRecord:
    user_id: int
    username: str
    password_hash: str
    password_salt: str
    created_at: str
    is_active: bool


@dataclass
class SessionRecord:
    session_id: str
    user_id: int
    expires_at: str


@dataclass
class SettingsRecord:
    parallel_enabled: bool
    max_concurrent: int
    tags: list[str]
    api_keys: dict[str, str]
    asset_selections: dict[str, str]


class AppDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._ensure_dir()
        self._init_schema()

    def _ensure_dir(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path.as_posix())
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS auth_identities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    provider_user_id TEXT NOT NULL,
                    profile_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(provider, provider_user_id),
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS pipeline_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT,
                    result_json TEXT,
                    speaker_required INTEGER NOT NULL DEFAULT 0,
                    speaker_submitted INTEGER NOT NULL DEFAULT 0,
                    note TEXT,
                    custom_name TEXT,
                    tags_json TEXT,
                    published INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS pipeline_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    step TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    detail TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES pipeline_jobs(job_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS queue_order (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    job_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    UNIQUE(user_id, job_id),
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS settings (
                    user_id INTEGER PRIMARY KEY,
                    parallel_enabled INTEGER NOT NULL DEFAULT 0,
                    max_concurrent INTEGER NOT NULL DEFAULT 1,
                    tags_json TEXT,
                    api_keys_json TEXT,
                    asset_selections_json TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS wechat_states (
                    state TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    redirect_url TEXT
                );
                """
            )

    def ensure_default_admin(self, username: str, password_hash: str, password_salt: str) -> int:
        existing = self.get_user_by_username(username)
        if existing:
            return existing.user_id
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (username, password_hash, password_salt, created_at, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (username, password_hash, password_salt, _utc_now()),
            )
            return int(cur.lastrowid)

    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if not row:
            return None
        return UserRecord(
            user_id=int(row["id"]),
            username=str(row["username"]),
            password_hash=str(row["password_hash"]),
            password_salt=str(row["password_salt"]),
            created_at=str(row["created_at"]),
            is_active=bool(row["is_active"]),
        )

    def get_user_by_id(self, user_id: int) -> Optional[UserRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return None
        return UserRecord(
            user_id=int(row["id"]),
            username=str(row["username"]),
            password_hash=str(row["password_hash"]),
            password_salt=str(row["password_salt"]),
            created_at=str(row["created_at"]),
            is_active=bool(row["is_active"]),
        )

    def get_user_by_identity(self, provider: str, provider_user_id: str) -> Optional[UserRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.* FROM users u
                JOIN auth_identities a ON a.user_id = u.id
                WHERE a.provider = ? AND a.provider_user_id = ?
                """,
                (provider, provider_user_id),
            ).fetchone()
        if not row:
            return None
        return UserRecord(
            user_id=int(row["id"]),
            username=str(row["username"]),
            password_hash=str(row["password_hash"]),
            password_salt=str(row["password_salt"]),
            created_at=str(row["created_at"]),
            is_active=bool(row["is_active"]),
        )

    def create_user(self, username: str, password_hash: str, password_salt: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (username, password_hash, password_salt, created_at, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (username, password_hash, password_salt, _utc_now()),
            )
            return int(cur.lastrowid)

    def upsert_identity(
        self,
        user_id: int,
        provider: str,
        provider_user_id: str,
        profile: Optional[dict[str, Any]],
    ) -> None:
        profile_json = json.dumps(profile or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_identities (user_id, provider, provider_user_id, profile_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider, provider_user_id)
                DO UPDATE SET user_id=excluded.user_id, profile_json=excluded.profile_json
                """,
                (user_id, provider, provider_user_id, profile_json, _utc_now()),
            )

    def create_session(self, user_id: int, session_id: Optional[str] = None) -> SessionRecord:
        sid = session_id or uuid.uuid4().hex
        expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, ?)",
                (sid, user_id, expires_at),
            )
        return SessionRecord(session_id=sid, user_id=user_id, expires_at=expires_at)

    def delete_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        expires_at = str(row["expires_at"])
        if _parse_datetime(expires_at) and _parse_datetime(expires_at) < datetime.utcnow():
            self.delete_session(session_id)
            return None
        return SessionRecord(
            session_id=str(row["session_id"]),
            user_id=int(row["user_id"]),
            expires_at=expires_at,
        )

    def save_settings(self, user_id: int, settings: SettingsRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (user_id, parallel_enabled, max_concurrent, tags_json, api_keys_json, asset_selections_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    parallel_enabled=excluded.parallel_enabled,
                    max_concurrent=excluded.max_concurrent,
                    tags_json=excluded.tags_json,
                    api_keys_json=excluded.api_keys_json,
                    asset_selections_json=excluded.asset_selections_json
                """,
                (
                    user_id,
                    1 if settings.parallel_enabled else 0,
                    int(settings.max_concurrent),
                    json.dumps(settings.tags, ensure_ascii=False),
                    json.dumps(settings.api_keys, ensure_ascii=False),
                    json.dumps(settings.asset_selections, ensure_ascii=False),
                ),
            )

    def load_settings(self, user_id: int) -> Optional[SettingsRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM settings WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return None
        return SettingsRecord(
            parallel_enabled=bool(row["parallel_enabled"]),
            max_concurrent=int(row["max_concurrent"]),
            tags=json.loads(row["tags_json"] or "[]"),
            api_keys=json.loads(row["api_keys_json"] or "{}"),
            asset_selections=json.loads(row["asset_selections_json"] or "{}"),
        )

    def load_all_settings(self) -> dict[int, SettingsRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM settings").fetchall()
        settings: dict[int, SettingsRecord] = {}
        for row in rows:
            settings[int(row["user_id"])] = SettingsRecord(
                parallel_enabled=bool(row["parallel_enabled"]),
                max_concurrent=int(row["max_concurrent"]),
                tags=json.loads(row["tags_json"] or "[]"),
                api_keys=json.loads(row["api_keys_json"] or "{}"),
                asset_selections=json.loads(row["asset_selections_json"] or "{}"),
            )
        return settings

    def save_job(self, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline_jobs (
                    job_id, user_id, status, created_at, started_at, finished_at, error,
                    result_json, speaker_required, speaker_submitted, note, custom_name, tags_json, published
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    error=excluded.error,
                    result_json=excluded.result_json,
                    speaker_required=excluded.speaker_required,
                    speaker_submitted=excluded.speaker_submitted,
                    note=excluded.note,
                    custom_name=excluded.custom_name,
                    tags_json=excluded.tags_json,
                    published=excluded.published
                """,
                (
                    payload["job_id"],
                    payload["user_id"],
                    payload["status"],
                    payload["created_at"],
                    payload.get("started_at"),
                    payload.get("finished_at"),
                    payload.get("error"),
                    json.dumps(payload.get("result"), ensure_ascii=False)
                    if payload.get("result") is not None
                    else None,
                    1 if payload.get("speaker_required") else 0,
                    1 if payload.get("speaker_submitted") else 0,
                    payload.get("note"),
                    payload.get("custom_name"),
                    json.dumps(payload.get("tags") or [], ensure_ascii=False),
                    1 if payload.get("published") else 0,
                ),
            )

    def save_steps(self, job_id: str, steps: Iterable[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pipeline_steps WHERE job_id = ?", (job_id,))
            conn.executemany(
                """
                INSERT INTO pipeline_steps (job_id, step, status, message, detail, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        job_id,
                        item.get("step", ""),
                        item.get("status", ""),
                        item.get("message", ""),
                        item.get("detail"),
                        item.get("timestamp", _utc_now()),
                    )
                    for item in steps
                ],
            )

    def delete_job(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pipeline_jobs WHERE job_id = ?", (job_id,))

    def load_jobs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM pipeline_jobs").fetchall()
            step_rows = conn.execute(
                "SELECT * FROM pipeline_steps ORDER BY id ASC"
            ).fetchall()
        steps_by_job: dict[str, list[dict[str, Any]]] = {}
        for row in step_rows:
            steps_by_job.setdefault(str(row["job_id"]), []).append(
                {
                    "step": row["step"],
                    "status": row["status"],
                    "message": row["message"],
                    "detail": row["detail"],
                    "timestamp": row["timestamp"],
                }
            )
        jobs: list[dict[str, Any]] = []
        for row in rows:
            jobs.append(
                {
                    "job_id": row["job_id"],
                    "user_id": int(row["user_id"]),
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "error": row["error"],
                    "result": json.loads(row["result_json"]) if row["result_json"] else None,
                    "speaker_required": bool(row["speaker_required"]),
                    "speaker_submitted": bool(row["speaker_submitted"]),
                    "note": row["note"],
                    "custom_name": row["custom_name"],
                    "tags": json.loads(row["tags_json"] or "[]"),
                    "published": bool(row["published"]),
                    "steps": steps_by_job.get(str(row["job_id"]), []),
                }
            )
        return jobs

    def save_queue_order(self, user_id: int, job_ids: list[str]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM queue_order WHERE user_id = ?", (user_id,))
            conn.executemany(
                "INSERT INTO queue_order (user_id, job_id, position) VALUES (?, ?, ?)",
                [(user_id, job_id, index) for index, job_id in enumerate(job_ids)],
            )

    def load_queue_order(self) -> dict[int, list[str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id, job_id, position FROM queue_order ORDER BY position ASC"
            ).fetchall()
        by_user: dict[int, list[str]] = {}
        for row in rows:
            by_user.setdefault(int(row["user_id"]), []).append(str(row["job_id"]))
        return by_user

    def upsert_wechat_state(self, state: str, redirect_url: Optional[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO wechat_states (state, created_at, redirect_url)
                VALUES (?, ?, ?)
                ON CONFLICT(state) DO UPDATE SET created_at=excluded.created_at, redirect_url=excluded.redirect_url
                """,
                (state, _utc_now(), redirect_url),
            )

    def consume_wechat_state(self, state: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT redirect_url FROM wechat_states WHERE state = ?",
                (state,),
            ).fetchone()
            conn.execute("DELETE FROM wechat_states WHERE state = ?", (state,))
        if not row:
            return None
        return row["redirect_url"]

    def has_any_jobs(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM pipeline_jobs").fetchone()
        return bool(row and row["cnt"])

    def migrate_from_pipeline_state(self, path: Path, admin_user_id: int) -> None:
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        settings = payload.get("settings", {}) if isinstance(payload.get("settings"), dict) else {}
        if settings:
            self.save_settings(
                admin_user_id,
                SettingsRecord(
                    parallel_enabled=bool(settings.get("parallel_enabled", False)),
                    max_concurrent=int(settings.get("max_concurrent", 1)),
                    tags=[str(t) for t in settings.get("tags", []) if str(t).strip()],
                    api_keys={
                        str(k): str(v)
                        for k, v in (settings.get("api_keys", {}) or {}).items()
                        if str(k).strip() and str(v).strip()
                    },
                    asset_selections={
                        str(k): str(v)
                        for k, v in (settings.get("asset_selections", {}) or {}).items()
                        if str(k).strip() and str(v).strip()
                    },
                ),
            )
        jobs = payload.get("jobs", []) or []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            self.save_job(
                {
                    "job_id": str(job.get("job_id")),
                    "user_id": admin_user_id,
                    "status": str(job.get("status", "failed")),
                    "created_at": job.get("created_at") or _utc_now(),
                    "started_at": job.get("started_at"),
                    "finished_at": job.get("finished_at"),
                    "error": job.get("error"),
                    "result": job.get("result"),
                    "speaker_required": bool(job.get("speaker_required", False)),
                    "speaker_submitted": bool(job.get("speaker_submitted", False)),
                    "note": job.get("note"),
                    "custom_name": job.get("custom_name"),
                    "tags": [str(t) for t in job.get("tags", []) or []],
                    "published": bool(job.get("published", False)),
                }
            )
            steps = job.get("steps", []) or []
            if isinstance(steps, list):
                self.save_steps(
                    str(job.get("job_id")),
                    [item for item in steps if isinstance(item, dict)],
                )
        stored_queue = payload.get("queue_order") if isinstance(payload.get("queue_order"), list) else []
        if stored_queue:
            self.save_queue_order(
                admin_user_id,
                [str(item) for item in stored_queue if item],
            )


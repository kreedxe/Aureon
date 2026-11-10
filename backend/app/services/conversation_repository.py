from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from app.schemas.conversations import (
    ConversationDetail,
    ConversationLanguage,
    ConversationListItem,
    ConversationMessageRecord,
    ConversationSummary,
    ConversationSummaryResponse,
)
from app.schemas.languages import LanguageCode


class ConversationRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    language TEXT NOT NULL CHECK(language IN ('auto', 'uz', 'ru', 'en')),
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL CHECK(status IN ('active', 'completed', 'failed')),
                    summary_json TEXT,
                    summary_error TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    text TEXT NOT NULL,
                    language TEXT NOT NULL CHECK(language IN ('uz', 'ru', 'en')),
                    timestamp TEXT NOT NULL,
                    language_probability REAL CHECK(
                        language_probability IS NULL OR
                        (language_probability >= 0 AND language_probability <= 1)
                    )
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS conversation_started_index "
                "ON conversations(started_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS conversation_messages_index "
                "ON conversation_messages(conversation_id, id)"
            )

    def recover_interrupted(self) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE conversations
                SET status = 'failed', ended_at = ?,
                    summary_error = 'Application closed before the conversation summary was saved.'
                WHERE status = 'active'
                """,
                (now,),
            )

    def create(self, language: ConversationLanguage) -> ConversationDetail:
        conversation_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO conversations (id, title, language, started_at, status)
                VALUES (?, 'New conversation', ?, ?, 'active')
                """,
                (conversation_id, language, now),
            )
        conversation = self.get(conversation_id)
        if conversation is None:
            raise RuntimeError("The new conversation could not be loaded from SQLite.")
        return conversation

    def list(self) -> list[ConversationListItem]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.*, COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN conversation_messages m ON m.conversation_id = c.id
                GROUP BY c.id
                ORDER BY c.started_at DESC
                """
            ).fetchall()
        return [self._list_item(row) for row in rows]

    def get(self, conversation_id: str) -> ConversationDetail | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT c.*, COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN conversation_messages m ON m.conversation_id = c.id
                WHERE c.id = ?
                GROUP BY c.id
                """,
                (conversation_id,),
            ).fetchone()
            if row is None:
                return None
            messages = connection.execute(
                """
                SELECT id, role, text, language, timestamp, language_probability
                FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY id
                """,
                (conversation_id,),
            ).fetchall()
        return ConversationDetail(
            **self._list_item(row).model_dump(),
            messages=[
                ConversationMessageRecord(
                    id=message["id"],
                    role=message["role"],
                    text=message["text"],
                    language=message["language"],
                    timestamp=message["timestamp"],
                    language_probability=message["language_probability"],
                )
                for message in messages
            ],
            summary=(
                ConversationSummaryResponse.model_validate(json.loads(row["summary_json"]))
                if row["summary_json"]
                else None
            ),
            summary_error=row["summary_error"],
        )

    def append_message(
        self,
        conversation_id: str,
        role: Literal["user", "assistant"],
        text: str,
        language: LanguageCode,
        language_probability: float | None = None,
    ) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO conversation_messages
                    (conversation_id, role, text, language, timestamp, language_probability)
                SELECT ?, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM conversations
                    WHERE id = ? AND status = 'active'
                )
                """,
                (
                    conversation_id,
                    role,
                    text,
                    language,
                    datetime.now(UTC).isoformat(),
                    language_probability,
                    conversation_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Active conversation {conversation_id} was not found.")
            if role == "user":
                first_message = connection.execute(
                    """
                    SELECT text FROM conversation_messages
                    WHERE conversation_id = ? AND role = 'user'
                    ORDER BY id LIMIT 1
                    """,
                    (conversation_id,),
                ).fetchone()
                if first_message is not None:
                    connection.execute(
                        """
                        UPDATE conversations
                        SET title = ?
                        WHERE id = ? AND title = 'New conversation'
                        """,
                        (self._title_from_opening(first_message["text"]), conversation_id),
                    )

    def complete(
        self,
        conversation_id: str,
        summary: ConversationSummary | None,
        summary_error: str | None = None,
    ) -> None:
        with self._connection() as connection:
            if summary is not None:
                connection.execute(
                    """
                    UPDATE conversations
                    SET title = ?, ended_at = ?, status = 'completed',
                        summary_json = ?, summary_error = NULL
                    WHERE id = ? AND status = 'active'
                    """,
                    (
                        summary.title,
                        datetime.now(UTC).isoformat(),
                        summary.model_dump_json(),
                        conversation_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE conversations
                    SET ended_at = ?, status = 'completed', summary_error = ?
                    WHERE id = ? AND status = 'active'
                    """,
                    (datetime.now(UTC).isoformat(), summary_error, conversation_id),
                )

    def fail(self, conversation_id: str, message: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE conversations
                SET ended_at = ?, status = 'failed', summary_error = ?
                WHERE id = ? AND status = 'active'
                """,
                (datetime.now(UTC).isoformat(), message, conversation_id),
            )

    def delete(self, conversation_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ? AND status != 'active'",
                (conversation_id,),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _list_item(row: sqlite3.Row) -> ConversationListItem:
        return ConversationListItem(
            id=row["id"],
            title=row["title"],
            language=row["language"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
            message_count=row["message_count"],
        )

    @staticmethod
    def _title_from_opening(text: str) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= 56:
            return normalized or "New conversation"
        return f"{normalized[:53].rstrip()}..."

"""任务存在本机，不上传。"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


def data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "GoodJob"
    root.mkdir(parents=True, exist_ok=True)
    return root


PRIORITY_HIGH = 0
PRIORITY_PLUS = 1
PRIORITY_MID = 2
PRIORITY_LOW = 3


@dataclass
class Task:
    id: int
    title: str
    done: bool
    created_at: datetime
    remind_at: datetime | None
    reminded: bool
    priority: int = PRIORITY_MID


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "tasks.db")
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                remind_at TEXT,
                reminded INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self.conn.commit()
        self._ensure_priority()

    def _ensure_priority(self) -> None:
        names = {row[1] for row in self.conn.execute("PRAGMA table_info(tasks)")}
        if "priority" not in names:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 2")
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def list_tasks(self) -> list[Task]:
        rows = self.conn.execute(
            "SELECT id, title, done, created_at, remind_at, reminded, priority FROM tasks ORDER BY id DESC"
        ).fetchall()
        return [self._row(row) for row in rows]

    def add_task(self, title: str, remind_at: datetime | None, priority: int = PRIORITY_MID) -> Task:
        created = datetime.now().replace(microsecond=0)
        rank = _priority(priority)
        cur = self.conn.execute(
            "INSERT INTO tasks (title, done, created_at, remind_at, reminded, priority) VALUES (?, 0, ?, ?, 0, ?)",
            (title.strip(), _stamp(created), _stamp(remind_at) if remind_at else None, rank),
        )
        self.conn.commit()
        return Task(
            id=int(cur.lastrowid),
            title=title.strip(),
            done=False,
            created_at=created,
            remind_at=remind_at,
            reminded=False,
            priority=rank,
        )

    def set_done(self, task_id: int, done: bool) -> None:
        self.conn.execute("UPDATE tasks SET done=? WHERE id=?", (1 if done else 0, task_id))
        self.conn.commit()

    def delete(self, task_id: int) -> None:
        self.conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.conn.commit()

    def update_task(self, task_id: int, title: str, remind_at: datetime | None, priority: int) -> None:
        self.conn.execute(
            "UPDATE tasks SET title=?, remind_at=?, priority=?, reminded=0 WHERE id=?",
            (title.strip(), _stamp(remind_at) if remind_at else None, _priority(priority), task_id),
        )
        self.conn.commit()

    def set_priority(self, task_id: int, priority: int) -> None:
        self.conn.execute("UPDATE tasks SET priority=? WHERE id=?", (_priority(priority), task_id))
        self.conn.commit()

    def carry_yesterday(self, today: datetime) -> int:
        day = today.date()
        yesterday = day - timedelta(days=1)
        moved = 0
        for task in self.list_tasks():
            if task.done:
                continue
            if task.remind_at is not None and task.remind_at.date() == yesterday:
                self.update_remind(
                    task.id,
                    datetime(day.year, day.month, day.day, task.remind_at.hour, task.remind_at.minute),
                )
                moved += 1
            elif task.remind_at is None and task.created_at.date() == yesterday:
                self.update_remind(task.id, datetime(day.year, day.month, day.day, 9, 0))
                moved += 1
        return moved

    def update_remind(self, task_id: int, remind_at: datetime | None) -> None:
        self.conn.execute(
            "UPDATE tasks SET remind_at=?, reminded=0 WHERE id=?",
            (_stamp(remind_at) if remind_at else None, task_id),
        )
        self.conn.commit()

    def due_tasks(self, now: datetime) -> list[Task]:
        rows = self.conn.execute(
            """
            SELECT id, title, done, created_at, remind_at, reminded, priority
            FROM tasks
            WHERE done=0 AND reminded=0 AND remind_at IS NOT NULL AND remind_at<=?
            ORDER BY remind_at
            """,
            (_stamp(now),),
        ).fetchall()
        return [self._row(row) for row in rows]

    def mark_reminded(self, task_ids: list[int]) -> None:
        if not task_ids:
            return
        self.conn.executemany(
            "UPDATE tasks SET reminded=1 WHERE id=?",
            [(task_id,) for task_id in task_ids],
        )
        self.conn.commit()

    def _row(self, row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            title=row["title"],
            done=bool(row["done"]),
            created_at=_parse(row["created_at"]),
            remind_at=_parse(row["remind_at"]) if row["remind_at"] else None,
            reminded=bool(row["reminded"]),
            priority=_priority(row["priority"]) if "priority" in row.keys() else PRIORITY_MID,
        )


def _priority(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return PRIORITY_MID
    if number < PRIORITY_HIGH or number > PRIORITY_LOW:
        return PRIORITY_MID
    return number


def load_config() -> dict:
    path = data_dir() / "config.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict) -> None:
    path = data_dir() / "config.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M")


def _parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")

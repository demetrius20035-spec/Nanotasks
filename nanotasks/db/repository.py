"""Репозиторий — все CRUD-операции над доменными объектами.

Принимает соединение (или курсор) DuckDB. Возвращает/принимает dataclass'ы
из :mod:`nanotasks.models`, так что остальной код не видит ни SQL, ни строк БД.
"""

from __future__ import annotations

import json

from ..models import Artifact, Project, Prompt, Task, TaskStatus, TaskType

_TASK_COLS = (
    "id, project_id, parent_id, key, title, type, body, file_path, "
    "depends_on, order_idx, status, created_at, updated_at"
)


def _to_task(row) -> Task:
    return Task(
        id=row[0],
        project_id=row[1],
        parent_id=row[2],
        key=row[3],
        title=row[4],
        type=TaskType(row[5]),
        body=row[6] or "",
        file_path=row[7],
        depends_on=json.loads(row[8] or "[]"),
        order_idx=row[9],
        status=TaskStatus(row[10]),
        created_at=str(row[11]) if row[11] is not None else None,
        updated_at=str(row[12]) if row[12] is not None else None,
    )


def _to_project(row) -> Project:
    return Project(
        id=row[0], name=row[1], description=row[2] or "", language=row[3] or "python",
        created_at=str(row[4]) if row[4] is not None else None,
    )


def _to_artifact(row) -> Artifact:
    return Artifact(
        id=row[0], task_id=row[1], prompt_id=row[2], model=row[3],
        content=row[4], file_path=row[5], version=row[6],
        created_at=str(row[7]) if row[7] is not None else None,
    )


class Repository:
    def __init__(self, con):
        self.con = con

    # ── Проекты ─────────────────────────────────────────────────────────────
    def create_project(self, project: Project) -> int:
        row = self.con.execute(
            "INSERT INTO projects(name, description, language) VALUES (?, ?, ?) RETURNING id",
            [project.name, project.description, project.language],
        ).fetchone()
        return row[0]

    def get_project(self, project_id: int) -> Project | None:
        row = self.con.execute(
            "SELECT id, name, description, language, created_at FROM projects WHERE id = ?",
            [project_id],
        ).fetchone()
        return _to_project(row) if row else None

    def list_projects(self) -> list[Project]:
        rows = self.con.execute(
            "SELECT id, name, description, language, created_at FROM projects ORDER BY id"
        ).fetchall()
        return [_to_project(r) for r in rows]

    def delete_project(self, project_id: int) -> None:
        self.con.execute(
            "DELETE FROM artifacts WHERE task_id IN (SELECT id FROM tasks WHERE project_id = ?)",
            [project_id],
        )
        self.con.execute(
            "DELETE FROM prompts WHERE task_id IN (SELECT id FROM tasks WHERE project_id = ?)",
            [project_id],
        )
        self.con.execute("DELETE FROM tasks WHERE project_id = ?", [project_id])
        self.con.execute("DELETE FROM events WHERE project_id = ?", [project_id])
        self.con.execute("DELETE FROM projects WHERE id = ?", [project_id])

    # ── Задачи ──────────────────────────────────────────────────────────────
    def add_task(self, task: Task) -> int:
        row = self.con.execute(
            "INSERT INTO tasks(project_id, parent_id, key, title, type, body, "
            "file_path, depends_on, order_idx, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            [
                task.project_id, task.parent_id, task.key, task.title,
                task.type.value, task.body, task.file_path,
                json.dumps(task.depends_on, ensure_ascii=False),
                task.order_idx, task.status.value,
            ],
        ).fetchone()
        return row[0]

    def get_task(self, task_id: int) -> Task | None:
        row = self.con.execute(
            f"SELECT {_TASK_COLS} FROM tasks WHERE id = ?", [task_id]
        ).fetchone()
        return _to_task(row) if row else None

    def get_task_by_key(self, project_id: int, key: str) -> Task | None:
        row = self.con.execute(
            f"SELECT {_TASK_COLS} FROM tasks WHERE project_id = ? AND key = ?",
            [project_id, key],
        ).fetchone()
        return _to_task(row) if row else None

    def list_tasks(self, project_id: int) -> list[Task]:
        rows = self.con.execute(
            f"SELECT {_TASK_COLS} FROM tasks WHERE project_id = ? ORDER BY order_idx, id",
            [project_id],
        ).fetchall()
        return [_to_task(r) for r in rows]

    def list_leaf_tasks(self, project_id: int) -> list[Task]:
        rows = self.con.execute(
            f"SELECT {_TASK_COLS} FROM tasks WHERE project_id = ? AND type <> 'group' "
            "ORDER BY order_idx, id",
            [project_id],
        ).fetchall()
        return [_to_task(r) for r in rows]

    def children(self, parent_id: int) -> list[Task]:
        rows = self.con.execute(
            f"SELECT {_TASK_COLS} FROM tasks WHERE parent_id = ? ORDER BY order_idx, id",
            [parent_id],
        ).fetchall()
        return [_to_task(r) for r in rows]

    def update_task_status(self, task_id: int, status: TaskStatus) -> None:
        self.con.execute(
            "UPDATE tasks SET status = ?, updated_at = now() WHERE id = ?",
            [status.value, task_id],
        )

    def status_counts(self, project_id: int) -> dict[str, int]:
        rows = self.con.execute(
            "SELECT status, COUNT(*) FROM tasks WHERE project_id = ? GROUP BY status",
            [project_id],
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    # ── Промпты ─────────────────────────────────────────────────────────────
    def save_prompt(self, task_id: int, role: str, content: str, model: str | None = None) -> int:
        row = self.con.execute(
            "INSERT INTO prompts(task_id, role, model, content) VALUES (?, ?, ?, ?) RETURNING id",
            [task_id, role, model, content],
        ).fetchone()
        return row[0]

    def latest_prompt(self, task_id: int) -> Prompt | None:
        row = self.con.execute(
            "SELECT id, task_id, role, model, content, created_at FROM prompts "
            "WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            [task_id],
        ).fetchone()
        if not row:
            return None
        return Prompt(
            id=row[0], task_id=row[1], role=row[2], model=row[3], content=row[4],
            created_at=str(row[5]) if row[5] is not None else None,
        )

    # ── Артефакты (код) ──────────────────────────────────────────────────────
    def save_artifact(
        self, task_id: int, content: str, prompt_id: int | None = None,
        model: str | None = None, file_path: str | None = None,
    ) -> int:
        version = self._next_version(task_id)
        row = self.con.execute(
            "INSERT INTO artifacts(task_id, prompt_id, model, content, file_path, version) "
            "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            [task_id, prompt_id, model, content, file_path, version],
        ).fetchone()
        return row[0]

    def _next_version(self, task_id: int) -> int:
        row = self.con.execute(
            "SELECT COALESCE(MAX(version), 0) FROM artifacts WHERE task_id = ?", [task_id]
        ).fetchone()
        return (row[0] or 0) + 1

    def latest_artifact(self, task_id: int) -> Artifact | None:
        row = self.con.execute(
            "SELECT id, task_id, prompt_id, model, content, file_path, version, created_at "
            "FROM artifacts WHERE task_id = ? ORDER BY version DESC, id DESC LIMIT 1",
            [task_id],
        ).fetchone()
        return _to_artifact(row) if row else None

    def latest_artifacts_by_keys(self, project_id: int, keys: list[str]) -> dict[str, Artifact]:
        """Последний артефакт для каждого ключа задачи. Нужен для сборки контекста."""
        result: dict[str, Artifact] = {}
        for key in keys:
            task = self.get_task_by_key(project_id, key)
            if task and task.id is not None:
                art = self.latest_artifact(task.id)
                if art:
                    result[key] = art
        return result

    # ── Лог событий ───────────────────────────────────────────────────────────
    def log_event(self, message: str, project_id: int | None = None,
                  task_id: int | None = None, level: str = "info") -> None:
        self.con.execute(
            "INSERT INTO events(project_id, task_id, level, message) VALUES (?, ?, ?, ?)",
            [project_id, task_id, level, message],
        )

    def list_events(self, project_id: int, limit: int = 200) -> list[tuple]:
        return self.con.execute(
            "SELECT created_at, level, task_id, message FROM events "
            "WHERE project_id = ? ORDER BY id DESC LIMIT ?",
            [project_id, limit],
        ).fetchall()

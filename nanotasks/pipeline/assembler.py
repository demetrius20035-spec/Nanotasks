"""Сборка дерева файлов проекта из артефактов в БД."""

from __future__ import annotations

import re
from pathlib import Path

from ..db import Repository
from ..models import DONE_STATES, TaskStatus


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\-.]+", "_", name.strip())
    return cleaned or "project"


def assemble(repo: Repository, project_id: int, output_dir: str) -> tuple[Path, list[str]]:
    """Пишет одобренные артефакты в output_dir/<имя проекта>/<file_path>.

    Возвращает (корень, список записанных путей относительно корня).
    """
    project = repo.get_project(project_id)
    if project is None:
        raise ValueError(f"Проект {project_id} не найден.")

    base = Path(output_dir) / _safe_name(project.name)
    written: list[str] = []
    for task in repo.list_leaf_tasks(project_id):
        if task.status not in DONE_STATES or not task.file_path:
            continue
        art = repo.latest_artifact(task.id)
        if art is None:
            continue
        dest = base / task.file_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(art.content, encoding="utf-8")
        repo.update_task_status(task.id, TaskStatus.WRITTEN)
        written.append(str(Path(task.file_path)))

    return base, written


def render_tree(repo: Repository, project_id: int) -> str:
    """ASCII-представление дерева пунктов с их статусами."""
    tasks = repo.list_tasks(project_id)
    by_parent: dict[int | None, list] = {}
    for t in tasks:
        by_parent.setdefault(t.parent_id, []).append(t)

    lines: list[str] = []

    def walk(parent_id: int | None, depth: int) -> None:
        for t in by_parent.get(parent_id, []):
            indent = "  " * depth
            marker = "•" if t.is_leaf else "▸"
            suffix = f"  → {t.file_path}" if t.file_path else ""
            lines.append(f"{indent}{marker} [{t.key}] {t.title}  ({t.status.value}){suffix}")
            walk(t.id, depth + 1)

    walk(None, 0)
    return "\n".join(lines)

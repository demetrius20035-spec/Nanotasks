"""Импорт TODO от модели-архитектора в базу.

Формат — иерархический YAML (см. examples/todo.example.yaml). Каждый узел может
иметь `children` (подпункты), образуя дерево пункт → подпункт → подподпункт.
Узлы типа `group` — это разделы (код не генерируется), остальные — листья.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import yaml

from .db import Repository
from .models import Project, Task, TaskStatus, TaskType


class ImportError_(Exception):
    """Ошибка структуры импортируемого TODO."""


def import_todo(repo: Repository, path: str) -> int:
    """Импортирует YAML-файл TODO как новый проект. Возвращает id проекта."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    proj = data.get("project")
    if not proj or not proj.get("name"):
        raise ImportError_("В файле нет блока `project` с полем `name`.")

    project_id = repo.create_project(
        Project(
            name=proj["name"],
            description=proj.get("description", "") or "",
            language=proj.get("language", "python") or "python",
        )
    )

    order = itertools.count()
    seen_keys: set[str] = set()

    def walk(nodes, parent_id: int | None) -> None:
        for node in nodes or []:
            if "key" not in node:
                raise ImportError_(f"У пункта нет поля `key`: {node!r}")
            key = str(node["key"])
            if key in seen_keys:
                raise ImportError_(f"Дублирующийся ключ пункта: {key!r}")
            seen_keys.add(key)

            try:
                ttype = TaskType(node.get("type", "code"))
            except ValueError as exc:
                raise ImportError_(
                    f"Пункт {key}: неизвестный type={node.get('type')!r}. "
                    f"Допустимо: {[t.value for t in TaskType]}"
                ) from exc

            status = TaskStatus.SKIPPED if ttype == TaskType.GROUP else TaskStatus.PENDING
            task = Task(
                project_id=project_id,
                parent_id=parent_id,
                key=key,
                title=node.get("title", key) or key,
                type=ttype,
                body=(node.get("body") or "").strip(),
                file_path=node.get("file"),
                depends_on=[str(k) for k in (node.get("depends_on") or [])],
                order_idx=next(order),
                status=status,
            )
            task_id = repo.add_task(task)
            walk(node.get("children"), task_id)

    walk(data.get("tasks"), None)

    _validate_dependencies(repo, project_id, seen_keys)
    repo.log_event(f"Импортирован проект из {path}: пунктов {len(seen_keys)}",
                   project_id=project_id)
    return project_id


def _validate_dependencies(repo: Repository, project_id: int, keys: set[str]) -> None:
    """Проверяем, что все depends_on указывают на существующие ключи."""
    for task in repo.list_tasks(project_id):
        for dep in task.depends_on:
            if dep not in keys:
                repo.log_event(
                    f"Пункт {task.key}: зависимость '{dep}' не найдена среди ключей проекта.",
                    project_id=project_id, task_id=task.id, level="warning",
                )

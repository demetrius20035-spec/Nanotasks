"""Цикл аудита большой моделью.

Аудитор видит ТЗ/ФС + весь текущий код + ошибки сборки и возвращает YAML:
  audit     — текстовый разбор (ошибки, архитектурные промахи);
  fixes     — правки существующих пунктов: [{key, instruction}] → фидбек + needs_fix;
  additions — новые пункты в формате импорта.
Результат сливается в ТОТ ЖЕ проект, после чего обычный прогон перегенерирует
только тронутые пункты — это и есть итеративная доводка кода.
"""

from __future__ import annotations

import itertools
from collections import deque

from ..db import Repository
from ..llm import LLMClient
from ..models import DONE_STATES, Task, TaskStatus, TaskType
from ..textutil import load_yaml_lenient
from .assembler import render_tree

AUDITOR_SYSTEM = (
    "Ты — ведущий архитектор и ревьюер кода. Тебе дают ТЗ/ФС, текущий код проекта "
    "целиком и (если есть) ошибки сборки/запуска. Найди ошибки, баги, архитектурные "
    "промахи и несостыковки между файлами.\n"
    "Верни СТРОГО YAML (без markdown-ограждений) с полями:\n"
    "  audit: |   — краткий разбор: что не так и почему.\n"
    "  fixes:     — список правок СУЩЕСТВУЮЩИХ пунктов, каждый {key, instruction}, "
    "где key — ключ пункта из дерева TODO, instruction — что именно исправить.\n"
    "  additions: — список НОВЫХ пунктов в формате импорта "
    "({key, title, type, file, depends_on, body}); [] если новых файлов не нужно.\n"
    "Ничего вне YAML не пиши."
)


def build_audit_input(repo: Repository, project_id: int, errors: str | None = None) -> str:
    project = repo.get_project(project_id)
    parts = [f"# Проект: {project.name}  (язык: {project.language})"]
    if project.spec:
        parts.append("## ТЗ/ФС\n" + project.spec)
    elif project.description:
        parts.append("## Описание\n" + project.description)

    parts.append("## Текущее дерево пунктов\n" + render_tree(repo, project_id))

    parts.append("## Текущий код")
    for task, art in repo.leaf_artifacts(project_id):
        path = task.file_path or f"(пункт {task.key})"
        parts.append(f"### {path}  [пункт {task.key}]\n```\n{art.content}\n```")

    if errors:
        parts.append("## Ошибки сборки/запуска\n" + errors)

    parts.append(
        "Верни YAML с полями audit, fixes (по ключам существующих пунктов) и additions."
    )
    return "\n\n".join(parts)


def parse_audit(raw: str) -> dict:
    data = load_yaml_lenient(raw)
    data.setdefault("audit", "")
    data.setdefault("fixes", [])
    data.setdefault("additions", [])
    return data


def run_audit(client: LLMClient, repo: Repository, project_id: int,
              errors: str | None = None, retries: int = 1) -> dict:
    user = build_audit_input(repo, project_id, errors)
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            return parse_audit(client.ask(AUDITOR_SYSTEM, user))
        except ValueError as exc:
            last = exc
    raise last  # type: ignore[misc]


def apply_audit(repo: Repository, project_id: int, parsed: dict, audit_id: int,
                cascade: bool = False) -> tuple[int, int]:
    """Применяет разбор: правки → фидбек+needs_fix, новые пункты → задачи.

    При cascade=True дополнительно переоткрывает пункты, зависящие от исправленных.
    """
    n_fix = 0
    fixed_keys: list[str] = []
    for fix in parsed.get("fixes") or []:
        key = str(fix.get("key", "")).strip()
        instruction = (fix.get("instruction") or fix.get("issue") or "").strip()
        if not key or not instruction:
            continue
        task = repo.get_task_by_key(project_id, key)
        if task is None:
            repo.log_event(f"Аудит: пункт {key} не найден — правка пропущена",
                           project_id=project_id, level="warning")
            continue
        repo.add_feedback(task.id, instruction, source="audit", audit_id=audit_id)
        repo.reopen_task(task.id)
        fixed_keys.append(key)
        n_fix += 1

    if cascade and fixed_keys:
        _cascade_reopen(repo, project_id, fixed_keys, audit_id)

    n_add = _add_nodes(repo, project_id, parsed.get("additions") or [])
    return n_fix, n_add


def _cascade_reopen(repo: Repository, project_id: int, seed_keys: list[str],
                    audit_id: int) -> int:
    """Транзитивно переоткрывает готовые пункты, зависящие от исправленных."""
    seen = set(seed_keys)
    queue: deque[str] = deque(seed_keys)
    count = 0
    while queue:
        key = queue.popleft()
        for dep in repo.dependents(project_id, [key]):
            if dep.key in seen:
                continue
            seen.add(dep.key)
            queue.append(dep.key)
            if dep.is_leaf and dep.status in DONE_STATES:
                repo.add_feedback(
                    dep.id,
                    f"Зависимость {key} изменилась — проверь совместимость и при "
                    f"необходимости поправь.",
                    source="audit", audit_id=audit_id,
                )
                repo.reopen_task(dep.id)
                count += 1
    if count:
        repo.log_event(f"Каскад: переоткрыто зависимых пунктов: {count}",
                       project_id=project_id)
    return count


def _add_nodes(repo: Repository, project_id: int, nodes: list) -> int:
    existing = repo.list_tasks(project_id)
    keys = {t.key for t in existing}
    order = itertools.count(start=max((t.order_idx for t in existing), default=0) + 1)
    count = 0

    def resolve_parent(node, default_parent):
        pk = node.get("parent")
        if pk:
            pt = repo.get_task_by_key(project_id, str(pk))
            if pt is not None:
                return pt.id
        return default_parent

    def walk(items, parent_id):
        nonlocal count
        for node in items or []:
            idx = next(order)
            key = str(node.get("key") or f"add-{idx}")
            if key in keys:           # ключ уже есть — это правка, а не добавление
                continue
            keys.add(key)
            try:
                ttype = TaskType(node.get("type", "code"))
            except ValueError:
                ttype = TaskType.CODE
            status = TaskStatus.SKIPPED if ttype == TaskType.GROUP else TaskStatus.PENDING
            task = Task(
                project_id=project_id, parent_id=resolve_parent(node, parent_id),
                key=key, title=node.get("title", key) or key, type=ttype,
                body=(node.get("body") or "").strip(), file_path=node.get("file"),
                depends_on=[str(k) for k in (node.get("depends_on") or [])],
                order_idx=idx, status=status,
            )
            tid = repo.add_task(task)
            count += 1
            walk(node.get("children"), tid)

    walk(nodes, None)
    return count

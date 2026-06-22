"""Сборка контекста — самое важное место системы.

Маленькая модель-кодер работает БЕЗ памяти и без доступа к остальному проекту.
Чтобы она не выдумывала сигнатуры, перед генерацией мы собираем «контракты»
её зависимостей (поле depends_on): путь файла + уже сгенерированный код (или,
если кода ещё нет, текстовое описание из ТЗ). Этот блок подмешивается в промпт.
"""

from __future__ import annotations

from ..db import Repository
from ..models import Task


def assemble_context(repo: Repository, task: Task) -> str:
    if not task.depends_on:
        return ""

    artifacts = repo.latest_artifacts_by_keys(task.project_id, task.depends_on)
    blocks: list[str] = []
    for key in task.depends_on:
        dep = repo.get_task_by_key(task.project_id, key)
        if dep is None:
            continue
        header = f"### Зависимость {key} — {dep.title}"
        if dep.file_path:
            header += f"  (файл: {dep.file_path})"

        art = artifacts.get(key)
        if art:
            blocks.append(f"{header}\n```\n{art.content.strip()}\n```")
        elif dep.body:
            blocks.append(f"{header}\nОписание (код ещё не сгенерирован): {dep.body}")
        else:
            blocks.append(header)

    return "\n\n".join(blocks)

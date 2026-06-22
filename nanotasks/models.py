"""Доменные модели и перечисления.

Намеренно простые dataclass'ы — это «язык» всей системы. БД, импортёр,
пайплайн и GUI обмениваются именно этими объектами.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskType(str, Enum):
    """Тип пункта TODO."""

    GROUP = "group"      # узел-раздел: код не генерируется, только группирует детей
    CODE = "code"        # исходный код
    YAML = "yaml"        # YAML-файл
    CONFIG = "config"    # конфиг (любой формат)
    DOC = "doc"          # документация / текст
    TEST = "test"        # тесты


class TaskStatus(str, Enum):
    """Состояние пункта в конвейере исполнения."""

    PENDING = "pending"            # ждёт генерации нано-промпта
    PROMPT_READY = "prompt_ready"  # нано-промпт сгенерирован
    CODE_READY = "code_ready"      # код сгенерирован, ждёт ревью человеком
    APPROVED = "approved"          # человек одобрил артефакт
    WRITTEN = "written"            # артефакт записан в дерево файлов
    FAILED = "failed"              # ошибка генерации
    BLOCKED = "blocked"            # заблокирован незавершёнными зависимостями
    SKIPPED = "skipped"            # узел-группа или пропущенный пункт


# Состояния, которые считаются «готово» для целей сборки дерева файлов.
DONE_STATES = {TaskStatus.APPROVED, TaskStatus.WRITTEN}


@dataclass
class Project:
    name: str
    description: str = ""
    language: str = "python"
    id: int | None = None
    created_at: str | None = None


@dataclass
class Task:
    project_id: int
    key: str
    title: str
    type: TaskType = TaskType.CODE
    id: int | None = None
    parent_id: int | None = None
    body: str = ""
    file_path: str | None = None
    depends_on: list[str] = field(default_factory=list)  # ключи задач-зависимостей
    order_idx: int = 0
    status: TaskStatus = TaskStatus.PENDING
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def is_leaf(self) -> bool:
        """Лист — это пункт, для которого реально генерируется артефакт."""
        return self.type != TaskType.GROUP


@dataclass
class Prompt:
    task_id: int
    role: str          # кто сгенерировал, напр. 'prompt_builder'
    content: str
    model: str | None = None
    id: int | None = None
    created_at: str | None = None


@dataclass
class Artifact:
    task_id: int
    content: str
    prompt_id: int | None = None
    model: str | None = None
    file_path: str | None = None
    version: int = 1
    id: int | None = None
    created_at: str | None = None

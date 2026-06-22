"""Оркестратор — конечный автомат, прогоняющий пункты TODO через конвейер.

Состояния пункта:
    pending → prompt_ready → code_ready → approved → written
                                   ↘ failed / blocked / skipped

Логика общая для CLI и GUI: они отличаются только колбэками `review` и `on_event`.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable

from ..config import Config
from ..db import Repository
from ..llm import LLMClient, LLMError
from ..models import DONE_STATES, Artifact, Task, TaskStatus
from .auditor import apply_audit, run_audit
from .coder import generate_code
from .context import assemble_context
from .prompt_builder import build_nano_prompt


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REGENERATE = "regenerate"
    SKIP = "skip"
    STOP = "stop"


EventFn = Callable[[str, Task, object], None]
ReviewFn = Callable[[Task, Artifact], ReviewDecision]
StopFn = Callable[[], bool]


class Orchestrator:
    def __init__(self, repo: Repository, config: Config,
                 prompt_client: LLMClient | None = None,
                 coder_client: LLMClient | None = None):
        self.repo = repo
        self.config = config
        self.prompt_client = prompt_client
        self.coder_client = coder_client

    # ── один пункт целиком: нано-промпт → код ────────────────────────────────
    def process_task(self, task: Task, language: str) -> Artifact:
        context = assemble_context(self.repo, task)
        # незакрытые замечания (от человека/аудита) + текущий код → исправление
        feedback = [f.content for f in self.repo.unresolved_feedback(task.id)]
        current = self.repo.latest_artifact(task.id)
        current_code = current.content if (current is not None and feedback) else None

        nano = build_nano_prompt(
            self.prompt_client, task, context, language, current_code, feedback
        )
        prompt_id = self.repo.save_prompt(
            task.id, "prompt_builder", nano, self.prompt_client.model
        )
        self.repo.update_task_status(task.id, TaskStatus.PROMPT_READY)

        code = generate_code(self.coder_client, nano)
        self.repo.save_artifact(
            task.id, code, prompt_id, self.coder_client.model, task.file_path
        )
        self.repo.update_task_status(task.id, TaskStatus.CODE_READY)
        return self.repo.latest_artifact(task.id)

    def _deps_ready(self, task: Task) -> bool:
        for key in task.depends_on:
            dep = self.repo.get_task_by_key(task.project_id, key)
            if dep is not None and dep.status not in DONE_STATES:
                return False
        return True

    def _approve(self, task: Task) -> None:
        # одобрение закрывает все замечания: они учтены в принятой версии
        self.repo.resolve_feedback(task.id)
        self.repo.update_task_status(task.id, TaskStatus.APPROVED)

    # ── волна аудита большой моделью ──────────────────────────────────────────
    def audit_round(self, project_id: int, auditor_client,
                    errors: str | None = None) -> tuple[int, dict, int, int]:
        """Аудит проекта: разбор → правки (needs_fix) + новые пункты.

        Возвращает (audit_id, parsed, число_правок, число_новых_пунктов).
        После этого обычный run() перегенерирует тронутые пункты.
        """
        parsed = run_audit(auditor_client, self.repo, project_id, errors)
        audit_id = self.repo.create_audit(
            project_id, auditor_client.model, parsed.get("audit", ""), errors or ""
        )
        n_fix, n_add = apply_audit(
            self.repo, project_id, parsed, audit_id, cascade=self.config.cascade_dependents
        )
        return audit_id, parsed, n_fix, n_add

    # ── полный прогон проекта ────────────────────────────────────────────────
    def run(self, project_id: int, *, review: ReviewFn | None = None,
            on_event: EventFn | None = None, stop: StopFn | None = None) -> None:
        emit = on_event or (lambda *a: None)
        should_stop = stop or (lambda: False)

        project = self.repo.get_project(project_id)
        if project is None:
            raise ValueError(f"Проект {project_id} не найден.")
        language = project.language

        for task in self.repo.list_leaf_tasks(project_id):
            if should_stop():
                break
            if task.status in DONE_STATES:
                continue
            if not self._deps_ready(task):
                self.repo.update_task_status(task.id, TaskStatus.BLOCKED)
                self.repo.log_event(
                    f"Пункт {task.key}: зависимости ещё не готовы.",
                    project_id, task.id, "warning",
                )
                emit("blocked", task, None)
                continue

            try:
                if task.status == TaskStatus.CODE_READY:
                    art = self.repo.latest_artifact(task.id)
                else:
                    emit("prompting", task, None)
                    art = self.process_task(task, language)
            except LLMError as exc:
                self.repo.update_task_status(task.id, TaskStatus.FAILED)
                self.repo.log_event(
                    f"Пункт {task.key}: ошибка модели: {exc}", project_id, task.id, "error"
                )
                emit("failed", task, str(exc))
                continue

            emit("code_ready", task, art)

            # авто-режим: одобряем без участия человека
            if review is None:
                self._approve(task)
                emit("approved", task, art)
                continue

            # режим ревью: крутимся, пока человек не решит
            while True:
                decision = review(task, art)
                if decision == ReviewDecision.APPROVE:
                    self._approve(task)
                    emit("approved", task, art)
                    break
                if decision == ReviewDecision.SKIP:
                    self.repo.update_task_status(task.id, TaskStatus.SKIPPED)
                    emit("skipped", task, art)
                    break
                if decision == ReviewDecision.STOP:
                    emit("stopped", task, art)
                    return
                if decision == ReviewDecision.REGENERATE:
                    try:
                        emit("prompting", task, None)
                        art = self.process_task(task, language)
                    except LLMError as exc:
                        self.repo.update_task_status(task.id, TaskStatus.FAILED)
                        emit("failed", task, str(exc))
                        break
                    emit("code_ready", task, art)

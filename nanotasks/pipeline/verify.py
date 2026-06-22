"""Верификация собранного проекта: запуск команд компиляции/тестов и сбор ошибок.

Команды берутся из конфига (секция `verify.commands`) и выполняются в каталоге
собранного дерева файлов. Их вывод (особенно ошибки) уходит аудитору.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifyResult:
    command: str
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def run_verification(commands: list[str], cwd: Path, timeout: int = 300) -> list[VerifyResult]:
    results: list[VerifyResult] = []
    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(cwd),
                capture_output=True, text=True, timeout=timeout,
            )
            output = ((proc.stdout or "") + (proc.stderr or "")).strip()
            results.append(VerifyResult(cmd, proc.returncode, output))
        except subprocess.TimeoutExpired:
            results.append(VerifyResult(cmd, -1, f"таймаут {timeout}с"))
        except Exception as exc:  # noqa: BLE001
            results.append(VerifyResult(cmd, -1, f"{type(exc).__name__}: {exc}"))
    return results


def format_errors(results: list[VerifyResult]) -> str:
    """Текст только по упавшим командам — для подачи аудитору."""
    blocks = [
        f"$ {r.command}\n(код выхода {r.exit_code})\n{r.output}"
        for r in results if not r.ok
    ]
    return "\n\n".join(blocks)

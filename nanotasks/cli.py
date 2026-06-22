"""Командный интерфейс Nanotasks.

Полный цикл без GUI:
    python -m nanotasks import examples/todo.example.yaml
    python -m nanotasks projects
    python -m nanotasks run 1            # с ревью на каждом пункте
    python -m nanotasks run 1 --auto     # без ревью
    python -m nanotasks assemble 1
    python -m nanotasks gui              # десктоп-интерфейс
"""

from __future__ import annotations

import argparse
import sys

from .config import Config
from .db import Database, Repository
from .importer import import_todo
from .llm import LLMError, build_client
from .pipeline import Orchestrator, ReviewDecision, assemble, render_tree


def _open(config_path: str | None):
    config = Config.load(config_path)
    db = Database(config.database_path)
    return config, db, Repository(db.con)


def cmd_import(args) -> None:
    config, db, repo = _open(args.config)
    try:
        pid = import_todo(repo, args.file)
        proj = repo.get_project(pid)
        print(f"Импортирован проект #{pid}: {proj.name}\n")
        print(render_tree(repo, pid))
    finally:
        db.close()


def cmd_projects(args) -> None:
    config, db, repo = _open(args.config)
    try:
        projects = repo.list_projects()
        if not projects:
            print("Проектов пока нет. Импортируй TODO: nanotasks import <файл.yaml>")
            return
        for p in projects:
            print(f"#{p.id}  {p.name}  [{p.language}]  {repo.status_counts(p.id)}")
    finally:
        db.close()


def cmd_show(args) -> None:
    config, db, repo = _open(args.config)
    try:
        proj = repo.get_project(args.project_id)
        if proj is None:
            print(f"Проект #{args.project_id} не найден.")
            return
        print(f"#{proj.id} {proj.name} — {proj.description}\n")
        print(render_tree(repo, proj.id))
    finally:
        db.close()


def _make_cli_review(repo: Repository):
    def review(task, art):
        prompt = repo.latest_prompt(task.id)
        print("\n" + "─" * 72)
        print(f"Пункт [{task.key}] {task.title}  →  {task.file_path or '(без файла)'}")
        if prompt:
            print("\n— Нано-промпт (постановщик) —\n" + prompt.content)
        print("\n— Сгенерированный код —\n" + (art.content if art else "(пусто)"))
        print("─" * 72)
        while True:
            ans = input("[a] одобрить  [r] перегенерировать  [s] пропустить  [q] стоп: ").strip().lower()
            if ans in ("a", "approve", ""):
                return ReviewDecision.APPROVE
            if ans in ("r", "regen", "regenerate"):
                return ReviewDecision.REGENERATE
            if ans in ("s", "skip"):
                return ReviewDecision.SKIP
            if ans in ("q", "quit", "stop"):
                return ReviewDecision.STOP
    return review


def cmd_run(args) -> None:
    config, db, repo = _open(args.config)
    try:
        prompt_client = build_client(config.model("prompt_builder"), "prompt_builder")
        coder_client = build_client(config.model("coder"), "coder")
        orch = Orchestrator(repo, config, prompt_client, coder_client)

        def on_event(kind, task, payload):
            if kind == "prompting":
                print(f"… [{task.key}] {task.title}: {prompt_client.model} → {coder_client.model}")
            elif kind == "blocked":
                print(f"⏸  [{task.key}] заблокирован: зависимости не готовы")
            elif kind == "failed":
                print(f"✗  [{task.key}] ошибка: {payload}")
            elif kind == "approved":
                print(f"✓  [{task.key}] одобрено")

        auto = args.auto or config.run_mode == "auto"
        review = None if auto else _make_cli_review(repo)
        orch.run(args.project_id, review=review, on_event=on_event)

        base, written = assemble(repo, args.project_id, config.output_dir)
        print(f"\nСобрано файлов: {len(written)} → {base}")
        for w in written:
            print(f"  {w}")
    finally:
        db.close()


def cmd_assemble(args) -> None:
    config, db, repo = _open(args.config)
    try:
        base, written = assemble(repo, args.project_id, config.output_dir)
        print(f"Собрано файлов: {len(written)} → {base}")
        for w in written:
            print(f"  {w}")
    finally:
        db.close()


def cmd_delete(args) -> None:
    config, db, repo = _open(args.config)
    try:
        repo.delete_project(args.project_id)
        print(f"Проект #{args.project_id} удалён.")
    finally:
        db.close()


def cmd_gui(args) -> None:
    from .ui.app import run_gui
    run_gui(args.config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nanotasks", description="Оркестратор нано-задач")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="путь к config.yaml (по умолчанию config/config.yaml)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", parents=[common], help="импорт TODO (YAML) как новый проект")
    p.add_argument("file")
    p.set_defaults(func=cmd_import)

    sub.add_parser("projects", parents=[common], help="список проектов").set_defaults(func=cmd_projects)

    p = sub.add_parser("show", parents=[common], help="дерево пунктов проекта")
    p.add_argument("project_id", type=int)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("run", parents=[common], help="прогнать конвейер по проекту")
    p.add_argument("project_id", type=int)
    p.add_argument("--auto", action="store_true", help="без ревью, одобрять автоматически")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("assemble", parents=[common], help="собрать дерево файлов из БД")
    p.add_argument("project_id", type=int)
    p.set_defaults(func=cmd_assemble)

    p = sub.add_parser("delete", parents=[common], help="удалить проект из БД")
    p.add_argument("project_id", type=int)
    p.set_defaults(func=cmd_delete)

    sub.add_parser("gui", parents=[common], help="запустить десктоп-GUI").set_defaults(func=cmd_gui)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except FileNotFoundError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    except LLMError as exc:
        print(f"Модель недоступна: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

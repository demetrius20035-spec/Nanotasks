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
import shutil
import sys
from pathlib import Path

import yaml

from .config import Config
from .db import Database, Repository
from .importer import import_todo, import_todo_data
from .llm import LLMError, build_client
from .pipeline import (
    Orchestrator, ReviewDecision, assemble, format_errors, render_tree,
    run_architect, run_verification,
)


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


def cmd_plan(args) -> None:
    """Архитектор: бриф → ТЗ+ФС+TODO (YAML) → импорт в базу."""
    config, db, repo = _open(args.config)
    try:
        brief = Path(args.brief).read_text(encoding="utf-8")
        client = build_client(config.model("architect"), "architect")
        print(f"Архитектор ({client.model}) составляет план…")
        plan = run_architect(client, brief, args.language)

        save_path = args.save or str(Path(args.brief).with_suffix("")) + ".plan.yaml"
        Path(save_path).write_text(
            yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        print(f"План сохранён: {save_path}")

        if not args.no_import:
            pid = import_todo_data(repo, plan, source=save_path)
            print(f"Импортирован проект #{pid}\n")
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
                note = input("Что исправить? (Enter — без замечаний): ").strip()
                if note:
                    repo.add_feedback(task.id, note, source="human")
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


def cmd_verify(args) -> None:
    config, db, repo = _open(args.config)
    try:
        base, _ = assemble(repo, args.project_id, config.output_dir)
        if not config.verify_commands:
            print("В конфиге пусто verify.commands — нечего запускать.")
            return
        for r in run_verification(config.verify_commands, base):
            mark = "OK  " if r.ok else f"FAIL({r.exit_code})"
            print(f"[{mark}] {r.command}")
            if not r.ok and r.output:
                print(r.output)
    finally:
        db.close()


def cmd_audit(args) -> None:
    config, db, repo = _open(args.config)
    try:
        base, _ = assemble(repo, args.project_id, config.output_dir)
        errors = ""
        if args.errors_file:
            errors = Path(args.errors_file).read_text(encoding="utf-8")
        elif not args.no_verify and config.verify_commands:
            errors = format_errors(run_verification(config.verify_commands, base))
            if errors:
                print("Ошибки верификации переданы аудитору:\n" + errors + "\n")

        auditor = build_client(config.model("auditor"), "auditor")
        orch = Orchestrator(repo, config)
        audit_id, parsed, n_fix, n_add = orch.audit_round(
            args.project_id, auditor, errors or None
        )
        print(f"\n=== Аудит #{audit_id} ===\n{parsed.get('audit', '')}")
        print(f"\nПравок существующих пунктов: {n_fix}; новых пунктов: {n_add}")
        if n_fix or n_add:
            print(f"Перегенерация: python -m nanotasks run {args.project_id}")
    finally:
        db.close()


def cmd_iterate(args) -> None:
    """Автономный цикл: прогон → сборка → верификация → аудит → повтор."""
    config, db, repo = _open(args.config)
    try:
        pb = build_client(config.model("prompt_builder"), "prompt_builder")
        cd = build_client(config.model("coder"), "coder")
        orch = Orchestrator(repo, config, pb, cd)

        def on_event(kind, task, payload):
            if kind in ("approved", "failed", "blocked"):
                print(f"  {kind:9} [{task.key}] {task.title}")

        for rnd in range(1, args.rounds + 1):
            print(f"\n########## Итерация {rnd}/{args.rounds} ##########")
            orch.run(args.project_id, review=None, on_event=on_event)
            base, written = assemble(repo, args.project_id, config.output_dir)
            print(f"Собрано {len(written)} файлов → {base}")

            if not config.verify_commands:
                print("verify.commands пуст — проверять нечем, останов.")
                break
            errors = format_errors(run_verification(config.verify_commands, base))
            if not errors:
                print("✓ Верификация чистая — проект собирается. Останов.")
                break

            print("Есть ошибки — запускаю аудит…")
            auditor = build_client(config.model("auditor"), "auditor")
            audit_id, _parsed, n_fix, n_add = orch.audit_round(args.project_id, auditor, errors)
            print(f"Аудит #{audit_id}: правок {n_fix}, новых пунктов {n_add}")
            if n_fix == 0 and n_add == 0:
                print("Аудит не дал правок — останов.")
                break
    finally:
        db.close()


def cmd_versions(args) -> None:
    config, db, repo = _open(args.config)
    try:
        task = repo.get_task_by_key(args.project_id, args.key)
        if task is None:
            print(f"Пункт {args.key} не найден.")
            return
        versions = repo.list_artifact_versions(task.id)
        print(f"Пункт [{task.key}] {task.title} — версий: {len(versions)}")
        for a in versions:
            print(f"  v{a.version}  {a.created_at}  {a.model}  ({len(a.content)} симв.)")
    finally:
        db.close()


def cmd_rollback(args) -> None:
    config, db, repo = _open(args.config)
    try:
        task = repo.get_task_by_key(args.project_id, args.key)
        if task is None:
            print(f"Пункт {args.key} не найден.")
            return
        art = repo.rollback_artifact(task.id, args.version)
        if art is None:
            print(f"У пункта {args.key} нет версии {args.version}.")
            return
        print(f"Откат [{task.key}] к содержимому v{args.version} → "
              f"новая v{art.version} (статус approved).")
    finally:
        db.close()


def cmd_export(args) -> None:
    config, db, repo = _open(args.config)
    try:
        base, written = assemble(repo, args.project_id, config.output_dir)
        archive = shutil.make_archive(str(base), "zip", root_dir=str(base))
        print(f"Экспортировано {len(written)} файлов → {archive}")
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

    p = sub.add_parser("plan", parents=[common], help="архитектор: бриф → ТЗ+ФС+TODO → импорт")
    p.add_argument("brief", help="файл с кратким брифом проекта")
    p.add_argument("--language", help="целевой язык кода")
    p.add_argument("--save", help="куда сохранить сгенерированный план (YAML)")
    p.add_argument("--no-import", action="store_true", help="только сгенерировать план, не импортировать")
    p.set_defaults(func=cmd_plan)

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

    p = sub.add_parser("verify", parents=[common], help="собрать и прогнать verify.commands")
    p.add_argument("project_id", type=int)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("audit", parents=[common], help="аудит большой моделью → правки + новые пункты")
    p.add_argument("project_id", type=int)
    p.add_argument("--errors-file", help="файл с текстом ошибок вместо авто-верификации")
    p.add_argument("--no-verify", action="store_true", help="не запускать verify.commands")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("iterate", parents=[common], help="авто-цикл: прогон → сборка → верификация → аудит")
    p.add_argument("project_id", type=int)
    p.add_argument("--rounds", type=int, default=3, help="максимум волн (по умолчанию 3)")
    p.set_defaults(func=cmd_iterate)

    p = sub.add_parser("versions", parents=[common], help="версии артефакта пункта")
    p.add_argument("project_id", type=int)
    p.add_argument("key", help="ключ пункта, напр. 2.1")
    p.set_defaults(func=cmd_versions)

    p = sub.add_parser("rollback", parents=[common], help="откатить пункт к старой версии")
    p.add_argument("project_id", type=int)
    p.add_argument("key", help="ключ пункта, напр. 2.1")
    p.add_argument("version", type=int, help="номер версии")
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser("export", parents=[common], help="собрать и упаковать проект в zip")
    p.add_argument("project_id", type=int)
    p.set_defaults(func=cmd_export)

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
    except KeyError as exc:
        print(f"Конфигурация: {exc}", file=sys.stderr)
        return 2
    except LLMError as exc:
        print(f"Модель недоступна: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"Ошибка данных: {exc}", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

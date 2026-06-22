from nanotasks.models import Project, Task, TaskStatus
from nanotasks.pipeline import assemble, format_errors, render_tree, run_verification


def test_assemble_writes_only_done(repo, config):
    pid = repo.create_project(Project(name="P"))
    a = repo.add_task(Task(project_id=pid, key="1", title="A", file_path="a.py"))
    repo.save_artifact(a, "CODE_A", file_path="a.py")
    repo.update_task_status(a, TaskStatus.APPROVED)
    b = repo.add_task(Task(project_id=pid, key="2", title="B", file_path="b.py"))
    repo.save_artifact(b, "CODE_B", file_path="b.py")  # остаётся pending — не пишем
    base, written = assemble(repo, pid, config.output_dir)
    assert written == ["a.py"]
    assert (base / "a.py").read_text() == "CODE_A"
    assert not (base / "b.py").exists()
    assert repo.get_task(a).status == TaskStatus.WRITTEN


def test_render_tree_contains_keys_and_status(repo):
    pid = repo.create_project(Project(name="P"))
    repo.add_task(Task(project_id=pid, key="1", title="Альфа", file_path="a.py"))
    tree = render_tree(repo, pid)
    assert "[1] Альфа" in tree and "pending" in tree


def test_verification_ok_and_fail(tmp_path):
    results = run_verification(
        ['python -c "print(1)"', 'python -c "import sys; sys.exit(2)"'], tmp_path
    )
    assert results[0].ok is True
    assert results[1].ok is False and results[1].exit_code == 2
    errors = format_errors(results)
    assert "sys.exit(2)" in errors  # в отчёт попадает только упавшая команда


def test_format_errors_empty_when_all_ok(tmp_path):
    results = run_verification(['python -c "print(1)"'], tmp_path)
    assert format_errors(results) == ""

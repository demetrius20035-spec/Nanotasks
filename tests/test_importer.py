import pytest

from nanotasks.importer import ImportError_, import_todo, import_todo_data
from nanotasks.models import TaskStatus, TaskType


def test_import_example(repo, examples_dir):
    pid = import_todo(repo, str(examples_dir / "todo.example.yaml"))
    proj = repo.get_project(pid)
    assert proj.name == "Todo CLI"
    assert "JSON" in proj.spec  # spec сохранён

    by_key = {t.key: t for t in repo.list_tasks(pid)}
    assert by_key["1"].type == TaskType.GROUP
    assert by_key["1"].status == TaskStatus.SKIPPED       # группа не генерируется
    assert by_key["1.1"].status == TaskStatus.PENDING     # лист ждёт генерации
    assert by_key["2.1"].depends_on == ["1.1"]
    # иерархия: 1.1 — ребёнок 1
    assert by_key["1.1"].parent_id == by_key["1"].id


def test_duplicate_key_rejected(repo):
    data = {
        "project": {"name": "P"},
        "tasks": [{"key": "1", "title": "A"}, {"key": "1", "title": "B"}],
    }
    with pytest.raises(ImportError_):
        import_todo_data(repo, data)


def test_unknown_type_rejected(repo):
    data = {"project": {"name": "P"}, "tasks": [{"key": "1", "title": "A", "type": "weird"}]}
    with pytest.raises(ImportError_):
        import_todo_data(repo, data)


def test_missing_project_rejected(repo):
    with pytest.raises(ImportError_):
        import_todo_data(repo, {"tasks": []})

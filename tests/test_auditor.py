from nanotasks.models import Project, Task, TaskStatus
from nanotasks.pipeline import apply_audit, parse_audit
from nanotasks.pipeline.architect import parse_plan, run_architect
from tests.fakes import ScriptedClient


def test_parse_audit_lenient_with_prose():
    d = parse_audit("Мой разбор:\naudit: всё плохо\nfixes: []\nadditions: []")
    assert d["audit"] == "всё плохо" and d["fixes"] == []


def test_parse_audit_defaults_missing_fields():
    d = parse_audit("audit: только текст")
    assert d["fixes"] == [] and d["additions"] == []


def test_apply_audit_fix_and_add(repo):
    pid = repo.create_project(Project(name="P"))
    t = repo.add_task(Task(project_id=pid, key="1", title="T", file_path="a.py"))
    repo.update_task_status(t, TaskStatus.APPROVED)
    audit_id = repo.create_audit(pid, "m", "sum")
    parsed = {
        "audit": "x",
        "fixes": [{"key": "1", "instruction": "почини"}],
        "additions": [{"key": "2", "title": "Новый", "type": "code", "file": "b.py", "body": "b"}],
    }
    n_fix, n_add = apply_audit(repo, pid, parsed, audit_id)
    assert (n_fix, n_add) == (1, 1)
    assert repo.get_task(t).status == TaskStatus.NEEDS_FIX
    assert len(repo.unresolved_feedback(t)) == 1
    assert repo.get_task_by_key(pid, "2") is not None


def test_apply_audit_skips_unknown_key(repo):
    pid = repo.create_project(Project(name="P"))
    audit_id = repo.create_audit(pid, "m", "s")
    parsed = {"fixes": [{"key": "404", "instruction": "x"}], "additions": []}
    n_fix, n_add = apply_audit(repo, pid, parsed, audit_id)
    assert (n_fix, n_add) == (0, 0)


def test_cascade_reopens_dependents(repo):
    pid = repo.create_project(Project(name="P"))
    a = repo.add_task(Task(project_id=pid, key="A", title="A", file_path="a.py"))
    b = repo.add_task(Task(project_id=pid, key="B", title="B", file_path="b.py", depends_on=["A"]))
    c = repo.add_task(Task(project_id=pid, key="C", title="C", file_path="c.py", depends_on=["B"]))
    for x in (a, b, c):
        repo.update_task_status(x, TaskStatus.APPROVED)
    audit_id = repo.create_audit(pid, "m", "s")
    apply_audit(repo, pid, {"fixes": [{"key": "A", "instruction": "fix"}], "additions": []},
                audit_id, cascade=True)
    assert repo.get_task(b).status == TaskStatus.NEEDS_FIX
    assert repo.get_task(c).status == TaskStatus.NEEDS_FIX


def test_no_cascade_by_default(repo):
    pid = repo.create_project(Project(name="P"))
    a = repo.add_task(Task(project_id=pid, key="A", title="A", file_path="a.py"))
    b = repo.add_task(Task(project_id=pid, key="B", title="B", file_path="b.py", depends_on=["A"]))
    for x in (a, b):
        repo.update_task_status(x, TaskStatus.APPROVED)
    audit_id = repo.create_audit(pid, "m", "s")
    apply_audit(repo, pid, {"fixes": [{"key": "A", "instruction": "fix"}], "additions": []}, audit_id)
    assert repo.get_task(b).status == TaskStatus.APPROVED  # без cascade B не трогаем


# ── архитектор ────────────────────────────────────────────────────────────────
def test_parse_plan_ok():
    d = parse_plan("project:\n  name: P\n  language: python\ntasks: []")
    assert d["project"]["name"] == "P"


def test_parse_plan_rejects_non_plan():
    import pytest
    with pytest.raises(ValueError):
        parse_plan("просто текст без плана")


def test_run_architect_retries_until_valid():
    client = ScriptedClient(["мусор без структуры", "project:\n  name: P\ntasks: []"])
    plan = run_architect(client, "бриф", retries=1)
    assert plan["project"]["name"] == "P"
    assert client.calls == 2

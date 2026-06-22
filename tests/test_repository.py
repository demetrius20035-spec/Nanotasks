import pytest

from nanotasks.models import Project, Task, TaskStatus, TaskType


def _project(repo, **kw):
    return repo.create_project(Project(name=kw.get("name", "P"),
                                       spec=kw.get("spec", ""),
                                       language=kw.get("language", "python")))


def test_project_roundtrip_with_spec(repo):
    pid = _project(repo, name="Demo", spec="ТЗ тут")
    proj = repo.get_project(pid)
    assert proj.name == "Demo"
    assert proj.spec == "ТЗ тут"
    assert [p.id for p in repo.list_projects()] == [pid]


def test_task_crud_and_lookup(repo):
    pid = _project(repo)
    tid = repo.add_task(Task(project_id=pid, key="1.1", title="T",
                             type=TaskType.CODE, file_path="a.py", depends_on=["1.2"]))
    t = repo.get_task(tid)
    assert t.key == "1.1" and t.depends_on == ["1.2"] and t.file_path == "a.py"
    assert repo.get_task_by_key(pid, "1.1").id == tid


def test_groups_excluded_from_leaves(repo):
    pid = _project(repo)
    repo.add_task(Task(project_id=pid, key="1", title="G", type=TaskType.GROUP))
    repo.add_task(Task(project_id=pid, key="1.1", title="L", type=TaskType.CODE))
    leaves = repo.list_leaf_tasks(pid)
    assert [t.key for t in leaves] == ["1.1"]


def test_artifact_versions_increment(repo):
    pid = _project(repo)
    tid = repo.add_task(Task(project_id=pid, key="1", title="T"))
    repo.save_artifact(tid, "one")
    repo.save_artifact(tid, "two")
    versions = repo.list_artifact_versions(tid)
    assert [a.version for a in versions] == [1, 2]
    assert repo.latest_artifact(tid).content == "two"


def test_feedback_resolve(repo):
    pid = _project(repo)
    tid = repo.add_task(Task(project_id=pid, key="1", title="T"))
    repo.add_feedback(tid, "fix A")
    repo.add_feedback(tid, "fix B", source="audit")
    assert len(repo.unresolved_feedback(tid)) == 2
    repo.resolve_feedback(tid)
    assert repo.unresolved_feedback(tid) == []


def test_rollback_makes_old_version_latest(repo):
    pid = _project(repo)
    tid = repo.add_task(Task(project_id=pid, key="1", title="T", file_path="a.py"))
    repo.save_artifact(tid, "V1", file_path="a.py")
    repo.save_artifact(tid, "V2", file_path="a.py")
    art = repo.rollback_artifact(tid, 1)
    assert art.version == 3 and art.content == "V1"
    assert repo.get_task(tid).status == TaskStatus.APPROVED


def test_rollback_missing_version(repo):
    pid = _project(repo)
    tid = repo.add_task(Task(project_id=pid, key="1", title="T"))
    repo.save_artifact(tid, "V1")
    assert repo.rollback_artifact(tid, 99) is None


def test_dependents(repo):
    pid = _project(repo)
    repo.add_task(Task(project_id=pid, key="A", title="A"))
    repo.add_task(Task(project_id=pid, key="B", title="B", depends_on=["A"]))
    repo.add_task(Task(project_id=pid, key="C", title="C", depends_on=["B"]))
    deps = {t.key for t in repo.dependents(pid, ["A"])}
    assert deps == {"B"}


def test_audit_round_increments(repo):
    pid = _project(repo)
    repo.create_audit(pid, "m", "first")
    repo.create_audit(pid, "m", "second")
    latest = repo.latest_audit(pid)
    assert latest.round == 2 and latest.summary == "second"


def test_delete_project_cascades(repo):
    pid = _project(repo)
    tid = repo.add_task(Task(project_id=pid, key="1", title="T"))
    repo.save_artifact(tid, "x")
    repo.add_feedback(tid, "note")
    repo.create_audit(pid, "m", "s")
    repo.delete_project(pid)
    assert repo.get_project(pid) is None
    assert repo.list_tasks(pid) == []
    assert repo.latest_audit(pid) is None

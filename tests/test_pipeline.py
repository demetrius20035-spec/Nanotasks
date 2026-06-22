from nanotasks.importer import import_todo
from nanotasks.models import Project, Task, TaskStatus, TaskType
from nanotasks.pipeline import Orchestrator, ReviewDecision, assemble, assemble_context
from nanotasks.pipeline.coder import generate_code
from nanotasks.pipeline.prompt_builder import build_nano_prompt
from tests.fakes import EchoPrompt, FlakyClient, MarkerCoder


# ── сборка контекста ──────────────────────────────────────────────────────────
def test_context_includes_dependency_code(repo):
    pid = repo.create_project(Project(name="P"))
    a = repo.add_task(Task(project_id=pid, key="A", title="Модель", file_path="a.py"))
    repo.save_artifact(a, "class A: ...", file_path="a.py")
    b = repo.add_task(Task(project_id=pid, key="B", title="B", depends_on=["A"]))
    ctx = assemble_context(repo, repo.get_task(b))
    assert "class A: ..." in ctx and "a.py" in ctx


def test_context_empty_without_deps(repo):
    pid = repo.create_project(Project(name="P"))
    t = repo.add_task(Task(project_id=pid, key="1", title="T"))
    assert assemble_context(repo, repo.get_task(t)) == ""


# ── промпт и код ────────────────────────────────────────────────────────────
def test_prompt_includes_feedback_and_current_code(repo):
    pid = repo.create_project(Project(name="P"))
    t = repo.get_task(repo.add_task(Task(project_id=pid, key="1", title="T", file_path="a.py")))
    out = build_nano_prompt(EchoPrompt(), t, context="", language="python",
                            current_code="OLD CODE", feedback=["почини"])
    assert "fb=True" in out and "cur=True" in out


def test_generate_code_strips_fences(repo):
    assert "```" not in generate_code(MarkerCoder(fence=True), "nano")


# ── оркестратор ───────────────────────────────────────────────────────────────
def test_auto_run_and_assemble(repo, config, examples_dir):
    pid = import_todo(repo, str(examples_dir / "todo.example.yaml"))
    Orchestrator(repo, config, EchoPrompt(), MarkerCoder(fence=True)).run(pid, review=None)
    assert repo.status_counts(pid).get("approved", 0) == 3
    base, written = assemble(repo, pid, config.output_dir)
    assert len(written) == 3
    assert "```" not in (base / "todoapp/models.py").read_text()


def test_review_skip_marks_leaves_skipped(repo, config):
    # независимые листья, чтобы skip не упирался в зависимости
    pid = repo.create_project(Project(name="P"))
    repo.add_task(Task(project_id=pid, key="1", title="A", file_path="a.py", body="x"))
    repo.add_task(Task(project_id=pid, key="2", title="B", file_path="b.py", body="y"))
    Orchestrator(repo, config, EchoPrompt(), MarkerCoder()).run(
        pid, review=lambda task, art: ReviewDecision.SKIP
    )
    assert all(t.status == TaskStatus.SKIPPED for t in repo.list_leaf_tasks(pid))


def test_review_stop_halts(repo, config, examples_dir):
    pid = import_todo(repo, str(examples_dir / "todo.example.yaml"))
    Orchestrator(repo, config, EchoPrompt(), MarkerCoder()).run(
        pid, review=lambda task, art: ReviewDecision.STOP
    )
    # первый лист сгенерирован (code_ready), но не одобрен; остановились
    assert repo.status_counts(pid).get("approved", 0) == 0


def test_blocked_when_dependency_not_ready(repo, config):
    pid = repo.create_project(Project(name="P"))
    b = repo.add_task(Task(project_id=pid, key="B", title="B", file_path="b.py",
                           depends_on=["A"], order_idx=0))
    a = repo.add_task(Task(project_id=pid, key="A", title="A", file_path="a.py", order_idx=1))
    Orchestrator(repo, config, EchoPrompt(), MarkerCoder()).run(pid, review=None)
    assert repo.get_task(b).status == TaskStatus.BLOCKED
    assert repo.get_task(a).status == TaskStatus.APPROVED


def test_coder_retry_on_transient_error(repo, config):
    pid = repo.create_project(Project(name="P"))
    t = repo.add_task(Task(project_id=pid, key="1", title="T", file_path="a.py", body="do"))
    orch = Orchestrator(repo, config, EchoPrompt(), FlakyClient("print('ok')\n", fail_times=1))
    art = orch.process_task(repo.get_task(t), "python")
    assert "print('ok')" in art.content


def test_feedback_injected_then_resolved(repo, config):
    pid = repo.create_project(Project(name="P"))
    t = repo.add_task(Task(project_id=pid, key="1", title="T", file_path="a.py", body="do"))
    orch = Orchestrator(repo, config, EchoPrompt(), MarkerCoder())
    orch.run(pid, review=None)
    assert "v1" in repo.latest_artifact(t).content

    repo.add_feedback(t, "почини", source="human")
    repo.reopen_task(t)
    orch.run(pid, review=None)

    assert repo.latest_artifact(t).version == 2
    assert "fixed" in repo.latest_artifact(t).content
    prompt = repo.latest_prompt(t)
    assert "fb=True" in prompt.content and "cur=True" in prompt.content
    assert repo.unresolved_feedback(t) == []

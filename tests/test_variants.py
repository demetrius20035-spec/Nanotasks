"""Ветвление вариантов: хранение кандидатов, выбор, судья, branch_task."""

from nanotasks.models import Project, Task, TaskStatus
from nanotasks.pipeline import (
    Orchestrator, generate_variants, parse_choice, select_best, variant_temperatures,
)
from tests.fakes import EchoPrompt, FlakyClient, RecordingCoder, ScriptedClient


def _leaf(repo, **kw):
    pid = repo.create_project(Project(name="P"))
    tid = repo.add_task(Task(project_id=pid, key="1", title="T",
                             file_path=kw.get("file_path", "a.py"), body="do"))
    return tid


# ── репозиторий: хранение и выбор вариантов ───────────────────────────────────
def test_save_variants_one_round_one_selected(repo):
    tid = _leaf(repo)
    ids = repo.save_variants(tid, [("A", "m"), ("B", "m"), ("C", "m")], file_path="a.py")
    assert len(ids) == 3
    variants = repo.list_variants(tid)
    assert [v.variant for v in variants] == [0, 1, 2]
    assert [v.content for v in variants] == ["A", "B", "C"]
    assert [v.selected for v in variants] == [True, False, False]
    assert {v.version for v in variants} == {1}           # всё в одном раунде
    assert repo.latest_artifact(tid).content == "A"        # текущий = выбранный


def test_select_variant_switches_current(repo):
    tid = _leaf(repo)
    repo.save_variants(tid, [("A", "m"), ("B", "m")])
    art = repo.select_variant(tid, 1)
    assert art.content == "B" and art.variant == 1 and art.selected is True
    assert repo.latest_artifact(tid).content == "B"
    assert sum(v.selected for v in repo.list_variants(tid)) == 1   # ровно один


def test_select_variant_missing_keeps_selection(repo):
    tid = _leaf(repo)
    repo.save_variants(tid, [("A", "m"), ("B", "m")])
    assert repo.select_variant(tid, 9) is None
    assert repo.latest_artifact(tid).content == "A"               # выбор не сбит
    assert sum(v.selected for v in repo.list_variants(tid)) == 1


def test_save_artifact_is_single_variant_round(repo):
    # обратная совместимость: одиночная генерация = раунд из одного кандидата
    tid = _leaf(repo)
    repo.save_artifact(tid, "one")
    assert repo.list_variants(tid)[0].selected is True
    repo.save_variants(tid, [("X", "m"), ("Y", "m")])             # version 2
    timeline = repo.list_artifact_versions(tid)                   # по одному на раунд
    assert [a.version for a in timeline] == [1, 2]
    assert [a.content for a in timeline] == ["one", "X"]


def test_list_variants_scoped_to_round(repo):
    tid = _leaf(repo)
    repo.save_variants(tid, [("A", "m"), ("B", "m")])             # v1
    repo.save_variants(tid, [("C", "m"), ("D", "m"), ("E", "m")])  # v2
    assert [v.content for v in repo.list_variants(tid)] == ["C", "D", "E"]
    assert [v.content for v in repo.list_variants(tid, version=1)] == ["A", "B"]
    # выбор в старом раунде не двигает «текущий» (последний раунд — v2)
    repo.select_variant(tid, 1, version=1)
    assert repo.latest_artifact(tid).content == "C"


def test_select_variant_old_round_returns_that_artifact(repo):
    tid = _leaf(repo)
    repo.save_variants(tid, [("A", "m"), ("B", "m")])             # v1
    repo.save_artifact(tid, "later")                              # v2
    art = repo.select_variant(tid, 1, version=1)
    assert art.content == "B" and art.version == 1


def test_rollback_uses_selected_variant(repo):
    tid = _leaf(repo)
    repo.save_variants(tid, [("A", "m"), ("B", "m")], file_path="a.py")  # v1
    repo.select_variant(tid, 1)                                          # текущий = B
    repo.save_artifact(tid, "v2body", file_path="a.py")                  # v2
    art = repo.rollback_artifact(tid, 1)                                 # вернуть раунд 1
    assert art.content == "B" and art.version == 3
    assert repo.get_task(tid).status == TaskStatus.APPROVED


def test_empty_variants_noop(repo):
    tid = _leaf(repo)
    assert repo.save_variants(tid, []) == []
    assert repo.list_variants(tid) == []
    assert repo.latest_artifact(tid) is None


# ── кодер: best-of-N ──────────────────────────────────────────────────────────
def test_variant_temperatures_spread_and_clamped():
    assert variant_temperatures(3) == [0.2, 0.5, 0.8]
    assert variant_temperatures(1) == [0.2]
    assert variant_temperatures(6)[-1] == 1.0
    assert all(t <= 1.0 for t in variant_temperatures(6))


def test_generate_variants_count_and_temperatures():
    coder = RecordingCoder()
    out = generate_variants(coder, "nano", n=3)
    assert out == ["# cand0", "# cand1", "# cand2"]      # ограждения сняты (strip)
    assert coder.temperatures == [0.2, 0.5, 0.8]


# ── судья (LLM-as-judge) ──────────────────────────────────────────────────────
def test_parse_choice_variants():
    assert parse_choice("ВЫБОР: 1\nпочему", 3) == 1
    assert parse_choice("выбор=2 потому что", 3) == 2
    assert parse_choice("думаю вариант 2 лучше", 3) == 2     # fallback: первое число
    assert parse_choice("вариант 1 плох, ВЫБОР: 0", 2) == 0  # строка ВЫБОР приоритетна
    assert parse_choice("ВЫБОР: 9", 3) == 0                  # вне диапазона → 0
    assert parse_choice("нет числа", 3) == 0
    assert parse_choice("ВЫБОР: 1", 1) == 0                  # один кандидат → 0


def test_select_best_single_candidate_no_call():
    judge = ScriptedClient(["ВЫБОР: 0"])
    task = Task(project_id=1, key="1", title="T", body="do")
    idx, reply = select_best(judge, task, ["only"])
    assert idx == 0 and reply == "" and judge.calls == 0


def test_select_best_picks_index():
    judge = ScriptedClient(["ВЫБОР: 1\nвторой полнее"])
    task = Task(project_id=1, key="1", title="T", body="do")
    idx, reply = select_best(judge, task, ["AAA", "BBB"])
    assert idx == 1 and "второй" in reply and judge.calls == 1


# ── оркестратор: branch_task ──────────────────────────────────────────────────
def test_branch_task_generates_variants_select_first(repo, config):
    tid = _leaf(repo)
    orch = Orchestrator(repo, config, EchoPrompt(), RecordingCoder())
    variants = orch.branch_task(repo.get_task(tid), "python", n=3)
    assert [v.variant for v in variants] == [0, 1, 2]
    assert repo.get_task(tid).status == TaskStatus.CODE_READY
    assert repo.latest_artifact(tid).variant == 0            # предварительно выбран первый
    assert repo.latest_artifact(tid).content == "# cand0"


def test_branch_task_judge_selects_best(repo, config):
    tid = _leaf(repo)
    judge = ScriptedClient(["ВЫБОР: 1\nлучше"])
    orch = Orchestrator(repo, config, EchoPrompt(), RecordingCoder())
    orch.branch_task(repo.get_task(tid), "python", n=2, judge_client=judge)
    art = repo.latest_artifact(tid)
    assert art.variant == 1 and art.content == "# cand1"
    assert judge.calls == 1


def test_branch_task_retries_transient_error(repo, config):
    tid = _leaf(repo)
    orch = Orchestrator(repo, config, EchoPrompt(), FlakyClient("X", fail_times=1))
    variants = orch.branch_task(repo.get_task(tid), "python", n=2)
    assert len(variants) == 2
    assert all(v.content == "X" for v in variants)

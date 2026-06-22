"""GUI-тесты панели вариантов (PySide6, offscreen).

Пропускаются там, где Qt не может инициализироваться (нет дисплея/libEGL) —
GUI в проекте опционален, поэтому основной набор от этого не краснеет.
"""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication           # noqa: E402

from nanotasks.config import Config                   # noqa: E402
from nanotasks.models import Project, Task            # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    try:
        app = QApplication.instance() or QApplication([])
    except Exception as exc:  # noqa: BLE001 — среда без GUI (нет libEGL/дисплея)
        pytest.skip(f"Qt не инициализируется: {exc}")
    yield app


@pytest.fixture
def window(qapp, tmp_path):
    from nanotasks.ui.app import MainWindow
    cfg = Config(database_path=str(tmp_path / "g.duckdb"), output_dir=str(tmp_path / "out"))
    win = MainWindow(cfg)
    yield win
    win.db.close()


def _seed(window, contents):
    repo = window.repo
    pid = repo.create_project(Project(name="P"))
    tid = repo.add_task(Task(project_id=pid, key="1", title="T", file_path="a.py"))
    repo.save_variants(tid, [(c, "m") for c in contents])
    window._refresh_projects()
    window.current_task_id = tid
    window._populate_versions(tid)
    return tid


def test_variant_panel_lists_and_previews(window):
    tid = _seed(window, ["AAA", "BBB", "CCC"])
    assert window.variant_combo.count() == 3
    assert window.variant_combo.isEnabled() and window.btn_select_variant.isEnabled()
    assert window.code_view.toPlainText() == "AAA"        # по умолчанию — выбранный (0)
    window.variant_combo.setCurrentIndex(2)               # превью другого кандидата
    assert window.code_view.toPlainText() == "CCC"
    assert window.repo.latest_artifact(tid).content == "AAA"   # превью не меняет выбор


def test_select_variant_commits(window):
    tid = _seed(window, ["AAA", "BBB", "CCC"])
    window.variant_combo.setCurrentIndex(2)
    window._on_select_variant()
    art = window.repo.latest_artifact(tid)
    assert art.variant == 2 and art.content == "CCC"
    assert "✓" in window.variant_combo.currentText()      # отмечен выбранный


def test_single_variant_disables_selection(window):
    _seed(window, ["only"])                               # один кандидат
    assert window.variant_combo.count() == 1
    assert not window.btn_select_variant.isEnabled()
    assert not window.variant_combo.isEnabled()
    assert window.code_view.toPlainText() == "only"


def test_version_switch_reloads_variants(window):
    # раунд 1 — три кандидата; раунд 2 — один (как ручная правка)
    repo = window.repo
    pid = repo.create_project(Project(name="P"))
    tid = repo.add_task(Task(project_id=pid, key="1", title="T", file_path="a.py"))
    repo.save_variants(tid, [("A0", "m"), ("A1", "m"), ("A2", "m")])   # v1
    repo.save_artifact(tid, "B", file_path="a.py")                     # v2
    window._refresh_projects()
    window.current_task_id = tid
    window._populate_versions(tid)
    # по умолчанию показан последний раунд (v2, один кандидат)
    assert window.version_combo.currentText() == "v2"
    assert window.variant_combo.count() == 1 and window.code_view.toPlainText() == "B"
    # переключаемся на v1 — снова три варианта
    window.version_combo.setCurrentIndex(0)
    assert window.version_combo.currentText() == "v1"
    assert window.variant_combo.count() == 3
    assert window.btn_select_variant.isEnabled()


def test_variant_diff_against_selected(window):
    # вариант 0 выбран по умолчанию (✓) и служит базой сравнения
    _seed(window, ["def f():\n    return 1\n",
                   "def f():\n    return 2\n",
                   "def f():\n    return 3\n"])
    assert window.btn_diff_variant.isEnabled()
    window.variant_combo.setCurrentIndex(2)                # показываем третий кандидат
    text = window._variant_diff_text()
    assert text is not None
    assert "вариант 0 ✓" in text and "вариант 2" in text   # направление база → показанный
    assert "-    return 1" in text and "+    return 3" in text


def test_variant_diff_none_when_showing_selected(window):
    _seed(window, ["AAA", "BBB", "CCC"])                   # по умолчанию показан выбранный (0)
    assert window._variant_diff_text() is None             # сам с собой не сравниваем


def test_variant_diff_disabled_for_single(window):
    _seed(window, ["only"])
    assert not window.btn_diff_variant.isEnabled()
    assert window._variant_diff_text() is None

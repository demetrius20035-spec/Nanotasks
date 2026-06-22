"""Десктоп-GUI Nanotasks (PySide6).

Слева — дерево пунктов TODO, справа — нано-промпт и сгенерированный код с
кнопками ревью. Прогон конвейера идёт в фоновом потоке, чтобы интерфейс не висел
во время обращений к моделям.
"""

from __future__ import annotations

import difflib
import queue

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTextEdit,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..config import Config
from ..db import Database, Repository
from ..importer import import_todo
from ..llm import LLMError, build_client
from ..pipeline import Orchestrator, ReviewDecision, assemble, format_errors, run_verification


# ─────────────────────────────────────────────────────────────────────────────
# Фоновый поток прогона конвейера
# ─────────────────────────────────────────────────────────────────────────────
class RunWorker(QThread):
    event = Signal(str, object, object)        # kind, task, payload
    reviewRequested = Signal(object, object)   # task, artifact
    done = Signal()
    failed = Signal(str)

    def __init__(self, config: Config, db: Database, project_id: int, auto: bool):
        super().__init__()
        self.config = config
        self.db = db
        self.project_id = project_id
        self.auto = auto
        self._decisions: queue.Queue = queue.Queue()
        self._stop = False

    def submit_decision(self, decision: ReviewDecision) -> None:
        self._decisions.put(decision)

    def request_stop(self) -> None:
        self._stop = True
        # разблокируем возможное ожидание ревью
        self._decisions.put(ReviewDecision.STOP)

    def _review(self, task, art) -> ReviewDecision:
        self.reviewRequested.emit(task, art)
        return self._decisions.get()

    def run(self) -> None:
        try:
            # отдельный курсор к той же БД — безопасно для другого потока
            repo = Repository(self.db.cursor())
            prompt_client = build_client(self.config.model("prompt_builder"), "prompt_builder")
            coder_client = build_client(self.config.model("coder"), "coder")
            orch = Orchestrator(repo, self.config, prompt_client, coder_client)
            orch.run(
                self.project_id,
                review=None if self.auto else self._review,
                on_event=lambda k, t, p: self.event.emit(k, t, p),
                stop=lambda: self._stop,
            )
            self.done.emit()
        except (LLMError, Exception) as exc:  # noqa: BLE001 — показываем любую ошибку в UI
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class AuditWorker(QThread):
    """Волна аудита в фоне: сборка → верификация → большая модель → правки."""

    log = Signal(str)
    done = Signal(int, int, str)   # n_fix, n_add, audit_text
    failed = Signal(str)

    def __init__(self, config: Config, db: Database, project_id: int):
        super().__init__()
        self.config = config
        self.db = db
        self.project_id = project_id

    def run(self) -> None:
        try:
            repo = Repository(self.db.cursor())
            base, _ = assemble(repo, self.project_id, self.config.output_dir)
            errors = ""
            if self.config.verify_commands:
                errors = format_errors(run_verification(self.config.verify_commands, base))
                self.log.emit("Верификация: " + ("есть ошибки" if errors else "чисто"))
            auditor = build_client(self.config.model("auditor"), "auditor")
            orch = Orchestrator(repo, self.config)
            _id, parsed, n_fix, n_add = orch.audit_round(self.project_id, auditor, errors or None)
            self.done.emit(n_fix, n_add, parsed.get("audit", ""))
        except (LLMError, Exception) as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Главное окно
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.db = Database(config.database_path)
        self.repo = Repository(self.db.con)
        self.current_project_id: int | None = None
        self.current_task_id: int | None = None
        self.worker: RunWorker | None = None
        self.audit_worker: AuditWorker | None = None
        self._awaiting_review = False
        self._items: dict[int, QTreeWidgetItem] = {}
        self._versions: list = []

        self.setWindowTitle("Nanotasks — оркестратор нано-задач")
        self.resize(1100, 720)
        self._build_ui()
        self._refresh_projects()

    # ── построение интерфейса ────────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        # Верхняя панель
        top = QHBoxLayout()
        self.project_combo = QComboBox()
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        top.addWidget(QLabel("Проект:"))
        top.addWidget(self.project_combo, 1)
        for text, slot in [
            ("Импорт TODO…", self._on_import),
            ("Обновить", self._refresh_tree),
            ("Удалить проект", self._on_delete),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            top.addWidget(b)
        root.addLayout(top)

        # Центральный сплиттер: дерево | детали
        splitter = QSplitter(Qt.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Пункт", "Статус", "Файл"])
        self.tree.setColumnWidth(0, 320)
        self.tree.itemSelectionChanged.connect(self._on_select_task)
        splitter.addWidget(self.tree)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Нано-промпт (постановщик):"))
        self.prompt_view = QTextEdit()
        self.prompt_view.setReadOnly(True)
        rl.addWidget(self.prompt_view, 1)

        # Строка версий: выбор версии · дифф · откат
        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("Версия:"))
        self.version_combo = QComboBox()
        self.version_combo.currentIndexChanged.connect(self._on_version_changed)
        ver_row.addWidget(self.version_combo, 1)
        self.btn_diff = QPushButton("Дифф с пред.")
        self.btn_rollback = QPushButton("Откатить к версии")
        self.btn_diff.clicked.connect(self._on_diff)
        self.btn_rollback.clicked.connect(self._on_rollback)
        ver_row.addWidget(self.btn_diff)
        ver_row.addWidget(self.btn_rollback)
        rl.addLayout(ver_row)

        self.code_label = QLabel("Код:")
        rl.addWidget(self.code_label)
        self.code_view = QTextEdit()
        self.code_view.setLineWrapMode(QTextEdit.NoWrap)
        self.code_view.setFont(QFont("monospace"))
        rl.addWidget(self.code_view, 2)
        self.btn_save_edit = QPushButton("💾 Сохранить правку как новую версию")
        self.btn_save_edit.clicked.connect(self._on_save_edit)
        rl.addWidget(self.btn_save_edit)

        rl.addWidget(QLabel("Замечания (незакрытые):"))
        self.feedback_view = QTextEdit()
        self.feedback_view.setReadOnly(True)
        self.feedback_view.setFixedHeight(80)
        rl.addWidget(self.feedback_view)

        review_row = QHBoxLayout()
        self.btn_approve = QPushButton("✓ Одобрить")
        self.btn_regen = QPushButton("↻ Перегенерировать")
        self.btn_skip = QPushButton("» Пропустить")
        self.btn_approve.clicked.connect(lambda: self._decide(ReviewDecision.APPROVE))
        self.btn_regen.clicked.connect(lambda: self._decide(ReviewDecision.REGENERATE))
        self.btn_skip.clicked.connect(lambda: self._decide(ReviewDecision.SKIP))
        for b in (self.btn_approve, self.btn_regen, self.btn_skip):
            b.setEnabled(False)
            review_row.addWidget(b)
        rl.addLayout(review_row)
        splitter.addWidget(right)
        splitter.setSizes([380, 720])
        root.addWidget(splitter, 1)

        # Нижняя панель: запуск + лог
        run_row = QHBoxLayout()
        self.btn_run = QPushButton("▶ Прогон (с ревью)")
        self.btn_auto = QPushButton("⏩ Прогон (авто)")
        self.btn_stop = QPushButton("■ Стоп")
        self.btn_assemble = QPushButton("🗂 Собрать")
        self.btn_audit = QPushButton("🔍 Аудит")
        self.btn_run.clicked.connect(lambda: self._start_run(auto=False))
        self.btn_auto.clicked.connect(lambda: self._start_run(auto=True))
        self.btn_stop.clicked.connect(self._stop_run)
        self.btn_assemble.clicked.connect(self._on_assemble)
        self.btn_audit.clicked.connect(self._start_audit)
        self.btn_stop.setEnabled(False)
        for b in (self.btn_run, self.btn_auto, self.btn_stop, self.btn_assemble, self.btn_audit):
            run_row.addWidget(b)
        root.addLayout(run_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setFixedHeight(140)
        root.addWidget(self.log)

        self.setCentralWidget(central)

    # ── данные ────────────────────────────────────────────────────────────────
    def _refresh_projects(self) -> None:
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for p in self.repo.list_projects():
            self.project_combo.addItem(f"#{p.id}  {p.name}", p.id)
        self.project_combo.blockSignals(False)
        if self.project_combo.count():
            self.project_combo.setCurrentIndex(self.project_combo.count() - 1)
            self._on_project_changed()

    def _on_project_changed(self) -> None:
        self.current_project_id = self.project_combo.currentData()
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        self.tree.clear()
        self._items = {}
        if self.current_project_id is None:
            return
        for t in self.repo.list_tasks(self.current_project_id):
            item = QTreeWidgetItem([f"[{t.key}] {t.title}", t.status.value, t.file_path or ""])
            item.setData(0, Qt.UserRole, t.id)
            self._items[t.id] = item
            parent = self._items.get(t.parent_id) if t.parent_id else None
            (parent.addChild(item) if parent else self.tree.addTopLevelItem(item))
        self.tree.expandAll()
        if self.current_task_id in self._items:
            self.tree.setCurrentItem(self._items[self.current_task_id])

    def _on_select_task(self) -> None:
        sel = self.tree.selectedItems()
        if not sel:
            return
        self.current_task_id = sel[0].data(0, Qt.UserRole)
        prompt = self.repo.latest_prompt(self.current_task_id)
        self.prompt_view.setPlainText(prompt.content if prompt else "")
        self._populate_versions(self.current_task_id)
        self._load_feedback(self.current_task_id)

    def _populate_versions(self, task_id: int) -> None:
        self._versions = self.repo.list_artifact_versions(task_id)
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        for idx, art in enumerate(self._versions):
            self.version_combo.addItem(f"v{art.version}", idx)
        if self._versions:
            self.version_combo.setCurrentIndex(len(self._versions) - 1)
        self.version_combo.blockSignals(False)
        self._show_selected_version()

    def _show_selected_version(self) -> None:
        idx = self.version_combo.currentData()
        if idx is None or not self._versions:
            self.code_view.clear()
            self.code_label.setText("Код:")
            return
        art = self._versions[idx]
        self.code_view.setPlainText(art.content)
        self.code_label.setText(f"Код (версия {art.version}):")

    def _on_version_changed(self) -> None:
        self._show_selected_version()

    def _load_feedback(self, task_id: int) -> None:
        items = self.repo.unresolved_feedback(task_id)
        self.feedback_view.setPlainText(
            "\n".join(f"• [{f.source}] {f.content}" for f in items) or "— нет —"
        )

    def _refresh_detail(self) -> None:
        if self.current_task_id is not None:
            self._populate_versions(self.current_task_id)
            self._load_feedback(self.current_task_id)

    def _on_diff(self) -> None:
        idx = self.version_combo.currentData()
        if idx is None or idx == 0:
            QMessageBox.information(self, "Дифф", "Нет предыдущей версии для сравнения.")
            return
        prev, cur = self._versions[idx - 1], self._versions[idx]
        diff = difflib.unified_diff(
            prev.content.splitlines(), cur.content.splitlines(),
            fromfile=f"v{prev.version}", tofile=f"v{cur.version}", lineterm="",
        )
        self._show_text(f"Дифф v{prev.version} → v{cur.version}", "\n".join(diff) or "(идентичны)")

    def _busy(self) -> bool:
        """Идёт фоновая запись в БД (активная генерация или аудит)?"""
        run_busy = self.worker is not None and self.worker.isRunning() and not self._awaiting_review
        audit_busy = self.audit_worker is not None and self.audit_worker.isRunning()
        return run_busy or audit_busy

    def _on_rollback(self) -> None:
        idx = self.version_combo.currentData()
        if idx is None or self.current_task_id is None:
            return
        if self._busy():
            QMessageBox.information(self, "Занято", "Дождись окончания прогона/аудита.")
            return
        version = self._versions[idx].version
        art = self.repo.rollback_artifact(self.current_task_id, version)
        if art:
            self._log(f"↩ откат к v{version} → новая v{art.version}")
            self._refresh_tree()
            self._refresh_detail()

    def _on_save_edit(self) -> None:
        if self.current_task_id is None:
            return
        if self._busy():
            QMessageBox.information(self, "Занято", "Дождись окончания прогона/аудита.")
            return
        task = self.repo.get_task(self.current_task_id)
        self.repo.save_artifact(
            self.current_task_id, self.code_view.toPlainText(),
            model="manual", file_path=task.file_path if task else None,
        )
        self._log("💾 сохранена ручная правка как новая версия")
        self._refresh_detail()

    def _show_text(self, title: str, text: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(700, 500)
        layout = QVBoxLayout(dlg)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setFont(QFont("monospace"))
        view.setPlainText(text)
        layout.addWidget(view)
        close = QPushButton("Закрыть")
        close.clicked.connect(dlg.accept)
        layout.addWidget(close)
        dlg.exec()

    # ── действия ────────────────────────────────────────────────────────────
    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выбери TODO (YAML)", "", "YAML (*.yaml *.yml)")
        if not path:
            return
        try:
            pid = import_todo(self.repo, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка импорта", str(exc))
            return
        self._log(f"Импортирован проект #{pid}")
        self._refresh_projects()

    def _on_delete(self) -> None:
        if self.current_project_id is None:
            return
        if QMessageBox.question(self, "Удалить", "Удалить проект целиком?") != QMessageBox.Yes:
            return
        self.repo.delete_project(self.current_project_id)
        self._refresh_projects()

    def _on_assemble(self) -> None:
        if self.current_project_id is None:
            return
        base, written = assemble(self.repo, self.current_project_id, self.config.output_dir)
        self._log(f"Собрано файлов: {len(written)} → {base}")
        self._refresh_tree()

    def _start_run(self, auto: bool) -> None:
        if self.current_project_id is None or (self.worker and self.worker.isRunning()):
            return
        self.worker = RunWorker(self.config, self.db, self.current_project_id, auto)
        self.worker.event.connect(self._on_event)
        self.worker.reviewRequested.connect(self._on_review_requested)
        self.worker.done.connect(self._on_run_done)
        self.worker.failed.connect(self._on_run_failed)
        self._set_running(True)
        self._log("▶ Старт прогона" + (" (авто)" if auto else " (с ревью)"))
        self.worker.start()

    def _stop_run(self) -> None:
        if self.worker:
            self.worker.request_stop()
            self._log("■ Останавливаю после текущего пункта…")

    def _start_audit(self) -> None:
        if self.current_project_id is None:
            return
        if (self.worker and self.worker.isRunning()) or (
            self.audit_worker and self.audit_worker.isRunning()
        ):
            return
        self.audit_worker = AuditWorker(self.config, self.db, self.current_project_id)
        self.audit_worker.log.connect(self._log)
        self.audit_worker.done.connect(self._on_audit_done)
        self.audit_worker.failed.connect(self._on_run_failed)
        self._set_running(True)
        self._log("🔍 Старт аудита большой моделью…")
        self.audit_worker.start()

    def _on_audit_done(self, n_fix: int, n_add: int, audit_text: str) -> None:
        self._set_running(False)
        self._log(f"🔍 Аудит: правок {n_fix}, новых пунктов {n_add}")
        self._refresh_tree()
        QMessageBox.information(
            self, "Аудит завершён",
            f"Правок существующих пунктов: {n_fix}\nНовых пунктов: {n_add}\n\n{audit_text}",
        )

    def _decide(self, decision: ReviewDecision) -> None:
        if not (self.worker and self._awaiting_review):
            return
        if decision == ReviewDecision.REGENERATE:
            note, ok = QInputDialog.getMultiLineText(
                self, "Перегенерация", "Что исправить? (можно пусто)", ""
            )
            sel = self.tree.selectedItems()
            if ok and note.strip() and sel:
                self.repo.add_feedback(sel[0].data(0, Qt.UserRole), note.strip(), source="human")
        self._awaiting_review = False
        self._enable_review(False)
        self.worker.submit_decision(decision)

    # ── реакция на события воркера ────────────────────────────────────────────
    def _on_event(self, kind: str, task, payload) -> None:
        labels = {
            "prompting": "… генерирую", "code_ready": "● код готов",
            "approved": "✓ одобрено", "skipped": "» пропущено",
            "blocked": "⏸ блокировка", "failed": "✗ ошибка", "stopped": "■ остановлено",
        }
        self._log(f"{labels.get(kind, kind)}  [{task.key}] {task.title}")
        if kind in ("approved", "skipped", "failed", "blocked"):
            self._refresh_tree()

    def _on_review_requested(self, task, art) -> None:
        self._awaiting_review = True
        self._refresh_tree()                       # показать свежие статусы
        item = self._items.get(task.id)
        if item is not None:
            self.tree.setCurrentItem(item)         # подтянет промпт/версии/замечания
        self._enable_review(True)
        self._log(f"⏸ ревью: [{task.key}] {task.title}")

    def _on_run_done(self) -> None:
        self._set_running(False)
        self._log("✓ Прогон завершён")
        self._refresh_tree()

    def _on_run_failed(self, message: str) -> None:
        self._set_running(False)
        self._log(f"✗ {message}")
        QMessageBox.critical(self, "Ошибка прогона", message)

    # ── вспомогательное ───────────────────────────────────────────────────────
    def _enable_review(self, enabled: bool) -> None:
        for b in (self.btn_approve, self.btn_regen, self.btn_skip):
            b.setEnabled(enabled)

    def _set_running(self, running: bool) -> None:
        self.btn_run.setEnabled(not running)
        self.btn_auto.setEnabled(not running)
        self.btn_assemble.setEnabled(not running)
        self.btn_audit.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        if not running:
            self._enable_review(False)
            self._awaiting_review = False

    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.worker.wait(3000)
        if self.audit_worker and self.audit_worker.isRunning():
            self.audit_worker.wait(3000)
        self.db.close()
        super().closeEvent(event)


def run_gui(config_path: str | None = None) -> int:
    config = Config.load(config_path)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(config)
    window.show()
    return app.exec()

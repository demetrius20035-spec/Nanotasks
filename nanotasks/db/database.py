"""Подключение к встроенной СУБД DuckDB и инициализация схемы.

Единственный модуль, который знает про конкретный движок. Хочешь поменять
DuckDB на другой встроенный движок — меняешь только здесь.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    """Тонкая обёртка над соединением DuckDB."""

    def __init__(self, path: str = "data/nanotasks.duckdb"):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(path)
        self._init_schema()

    def _init_schema(self) -> None:
        script = SCHEMA_PATH.read_text(encoding="utf-8")
        # DuckDB-драйвер исполняет по одному оператору — режем скрипт по ';'.
        for statement in script.split(";"):
            if statement.strip():
                self.con.execute(statement)
        self._migrate()

    def _migrate(self) -> None:
        """Однократные миграции для БД, созданных более ранней схемой.

        Проверяем наличие колонок и добавляем только отсутствующие: в DuckDB
        `ADD COLUMN IF NOT EXISTS` затирает значения дефолтом, так что повторять
        его на каждом старте нельзя.
        """
        cols = {
            r[0] for r in self.con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'artifacts'"
            ).fetchall()
        }
        if "variant" not in cols:
            self.con.execute("ALTER TABLE artifacts ADD COLUMN variant INTEGER DEFAULT 0")
        if "selected" not in cols:
            self.con.execute("ALTER TABLE artifacts ADD COLUMN selected BOOLEAN DEFAULT TRUE")

    def cursor(self):
        """Отдельный курсор для работы из другого потока (GUI-воркер)."""
        return self.con.cursor()

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

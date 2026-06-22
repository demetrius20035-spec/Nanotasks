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

    def cursor(self):
        """Отдельный курсор для работы из другого потока (GUI-воркер)."""
        return self.con.cursor()

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

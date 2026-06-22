"""Слой доступа к данным (DAL).

Вся работа с БД спрятана здесь. Сейчас движок — DuckDB (встроенная, не SQLite),
но репозиторий пользуется почти стандартным SQL, поэтому замена на другой
встроенный движок (например Firebird embedded) сводится к правке `database.py`.
"""

from .database import Database
from .repository import Repository

__all__ = ["Database", "Repository"]

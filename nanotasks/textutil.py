"""Разбор «грязного» вывода моделей: markdown-ограждения и YAML среди прозы.

Маленькие/средние модели часто добавляют пояснения вокруг ответа и оборачивают
его в ```-блоки. Эти функции достают полезное содержимое устойчиво.
"""

from __future__ import annotations

import re

import yaml

_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
# Строка-ключ верхнего уровня: «key:» либо «key: значение».
_TOP_KEY_RE = re.compile(r"^[A-Za-z_][\w-]*:(\s.*)?$")


def strip_code_fences(text: str) -> str:
    """Возвращает содержимое самого длинного ```-блока, либо текст как есть."""
    text = text.strip()
    blocks = _FENCE_RE.findall(text)
    if blocks:
        return max(blocks, key=len).strip("\n")
    return text


def load_yaml_lenient(raw: str) -> dict:
    """YAML из ответа модели, даже если он обёрнут в прозу/ограждения.

    Сначала пробуем как есть; если не вышло — отрезаем ведущую прозу до первой
    строки, похожей на YAML-ключ верхнего уровня.
    """
    text = strip_code_fences(raw).strip()
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        pass

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _TOP_KEY_RE.match(line):
            try:
                data = yaml.safe_load("\n".join(lines[i:]))
                if isinstance(data, dict):
                    return data
            except yaml.YAMLError:
                continue
    raise ValueError("Не удалось разобрать YAML из ответа модели:\n" + raw[:500])

#!/bin/bash
# SessionStart-hook: готовит окружение веб-сессии Claude Code —
# ставит зависимости, чтобы сразу работали тесты и запуск проекта.
set -euo pipefail

# Только в удалённом окружении (Claude Code on the web), локально не вмешиваемся.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# Идемпотентно: pip пропустит уже установленное, контейнер кешируется.
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet pytest

# Системные библиотеки для Qt/PySide6 — чтобы GUI-тесты шли offscreen, а не
# пропускались. Best-effort: при недоступности apt тесты GUI просто заскипятся.
if command -v apt-get >/dev/null 2>&1; then
  (apt-get update -qq && apt-get install -y -qq --no-install-recommends \
     libegl1 libgl1 libxkbcommon0 libdbus-1-3) >/dev/null 2>&1 || \
     echo "session-start: системные Qt-библиотеки не установлены — GUI-тесты пропустятся" >&2
fi

# Чтобы пакет nanotasks импортировался из любого каталога сессии.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PYTHONPATH=\"${CLAUDE_PROJECT_DIR:-.}\"" >> "$CLAUDE_ENV_FILE"
fi

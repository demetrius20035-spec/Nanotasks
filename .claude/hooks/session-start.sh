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

# Чтобы пакет nanotasks импортировался из любого каталога сессии.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PYTHONPATH=\"${CLAUDE_PROJECT_DIR:-.}\"" >> "$CLAUDE_ENV_FILE"
fi

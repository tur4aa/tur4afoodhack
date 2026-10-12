#!/usr/bin/env bash
# Запуск бота из папки проекта (используется и вручную, и launchd/systemd).
set -euo pipefail
cd "$(dirname "$0")/.."
exec ./.venv/bin/python -m bot

#!/usr/bin/env bash
# Синхронизирует скилл из dotfiles (ведущая копия) в этот репозиторий.
# Ведущая копия живёт в ~/dotfiles/claude/.claude/skills/forgeAi3d и раздаётся
# через stow в ~/.claude/skills. Здесь лежит копия для тех, у кого dotfiles нет.
set -euo pipefail

SRC="${FORGEAI3D_SKILL_SRC:-$HOME/dotfiles/claude/.claude/skills/forgeAi3d}"
DST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/skill/forgeAi3d"

if [[ ! -d "$SRC" ]]; then
  echo "Ведущей копии нет: $SRC" >&2
  echo "Задай путь через FORGEAI3D_SKILL_SRC, если dotfiles лежат в другом месте." >&2
  exit 1
fi

if [[ "${1:-}" == "--check" ]]; then
  if diff -rq "$SRC" "$DST" >/dev/null 2>&1; then
    echo "Копия в репозитории совпадает с dotfiles."
  else
    echo "Копии разошлись:"
    diff -rq "$SRC" "$DST" || true
    echo
    echo "Синхронизировать: scripts/sync-skill.sh"
    exit 1
  fi
  exit 0
fi

rm -rf "$DST"
mkdir -p "$(dirname "$DST")"
cp -R "$SRC" "$DST"
echo "Скилл скопирован: $SRC -> $DST"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_DIR/front"

if npm run build; then
  echo "前端构建完成"
  exit 0
fi

echo "首次前端构建失败，正在安装依赖后重试..."
if npm install; then
  :
else
  install_exit_code=$?
  exit "$install_exit_code"
fi

if npm run build; then
  echo "前端构建完成"
  exit 0
else
  build_exit_code=$?
  exit "$build_exit_code"
fi

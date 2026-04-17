#!/usr/bin/env bash
set -euo pipefail

SOURCE_WORKTREE=""
SOURCE_BRANCH=""
TARGET_BRANCH="master"
DELETE_BRANCH=0

usage() {
  cat <<'EOF'
Usage: merge_worktree_to_master.sh [options]

Options:
  --source-worktree PATH   Source worktree path
  --source-branch NAME     Source branch name
  --target-branch NAME     Target branch name, default: master
  --delete-branch          Delete the merged local source branch
  -h, --help               Show this help message

One of --source-worktree or --source-branch is required.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-worktree)
      SOURCE_WORKTREE="${2:-}"
      shift 2
      ;;
    --source-branch)
      SOURCE_BRANCH="${2:-}"
      shift 2
      ;;
    --target-branch)
      TARGET_BRANCH="${2:-}"
      shift 2
      ;;
    --delete-branch)
      DELETE_BRANCH=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[错误] 未知参数: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

log_info() {
  printf '[信息] %s\n' "$1"
}

log_warn() {
  printf '[提示] %s\n' "$1" >&2
}

worktree_registered() {
  local repo_root="$1"
  local worktree_path="$2"
  local resolved_path

  resolved_path="$(resolve_full_path "$worktree_path")"
  while IFS= read -r line; do
    if [[ "$line" == worktree\ * ]]; then
      if [[ "$(resolve_full_path "${line#worktree }")" == "$resolved_path" ]]; then
        return 0
      fi
    fi
  done < <(git -C "$repo_root" worktree list --porcelain)

  return 1
}

remove_leftover_worktree_dir() {
  local worktree_path="$1"
  local attempt

  if [[ ! -e "$worktree_path" ]]; then
    return 0
  fi

  for attempt in 1 2 3; do
    rm -rf "$worktree_path" 2>/dev/null || true
    if [[ ! -e "$worktree_path" ]]; then
      return 0
    fi
    sleep 1
  done

  return 1
}

remove_worktree_safely() {
  local repo_root="$1"
  local worktree_path="$2"

  if ! git -C "$repo_root" worktree remove "$worktree_path"; then
    if worktree_registered "$repo_root" "$worktree_path"; then
      return 1
    fi
  fi

  remove_leftover_worktree_dir "$worktree_path" || {
    echo "[错误] Git 已移除 worktree 记录，但目录仍被其它进程占用: $worktree_path" >&2
    echo "[错误] 请关闭占用该目录的终端、编辑器、隧道进程（如 cloudflared）后，再手动删除该空目录。" >&2
    return 1
  }
}

resolve_full_path() {
  python - "$1" <<'PY'
import os
import sys
print(os.path.abspath(sys.argv[1]))
PY
}

path_is_inside() {
  python - "$1" "$2" <<'PY'
import os
import sys
path = os.path.abspath(sys.argv[1])
root = os.path.abspath(sys.argv[2])
try:
    common = os.path.commonpath([path, root])
except ValueError:
    print("0")
    raise SystemExit(0)
print("1" if common == root else "0")
PY
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
CURRENT_DIR="$(pwd)"

if [[ -n "$SOURCE_WORKTREE" ]]; then
  SOURCE_WORKTREE="$(resolve_full_path "$SOURCE_WORKTREE")"
fi

declare -A WORKTREE_TO_BRANCH=()
declare -A BRANCH_TO_WORKTREE=()
CURRENT_WORKTREE=""
CURRENT_BRANCH=""

while IFS= read -r line; do
  if [[ -z "$line" ]]; then
    if [[ -n "$CURRENT_WORKTREE" ]]; then
      WORKTREE_TO_BRANCH["$CURRENT_WORKTREE"]="$CURRENT_BRANCH"
      if [[ -n "$CURRENT_BRANCH" ]]; then
        BRANCH_TO_WORKTREE["$CURRENT_BRANCH"]="$CURRENT_WORKTREE"
      fi
    fi
    CURRENT_WORKTREE=""
    CURRENT_BRANCH=""
    continue
  fi

  if [[ "$line" == worktree\ * ]]; then
    CURRENT_WORKTREE="$(resolve_full_path "${line#worktree }")"
    continue
  fi

  if [[ "$line" == branch\ refs/heads/* ]]; then
    CURRENT_BRANCH="${line#branch refs/heads/}"
  fi
done < <(git -C "$REPO_ROOT" worktree list --porcelain)

if [[ -n "$CURRENT_WORKTREE" ]]; then
  WORKTREE_TO_BRANCH["$CURRENT_WORKTREE"]="$CURRENT_BRANCH"
  if [[ -n "$CURRENT_BRANCH" ]]; then
    BRANCH_TO_WORKTREE["$CURRENT_BRANCH"]="$CURRENT_WORKTREE"
  fi
fi

SOURCE_ENTRY_WORKTREE=""
SOURCE_ENTRY_BRANCH=""

if [[ -n "$SOURCE_WORKTREE" ]]; then
  if [[ -z "${WORKTREE_TO_BRANCH[$SOURCE_WORKTREE]+x}" ]]; then
    echo "[错误] 未找到对应的 worktree: $SOURCE_WORKTREE" >&2
    exit 1
  fi
  SOURCE_ENTRY_WORKTREE="$SOURCE_WORKTREE"
  SOURCE_ENTRY_BRANCH="${WORKTREE_TO_BRANCH[$SOURCE_WORKTREE]}"
fi

if [[ -n "$SOURCE_BRANCH" ]]; then
  if [[ -n "$SOURCE_ENTRY_WORKTREE" && "$SOURCE_ENTRY_BRANCH" != "$SOURCE_BRANCH" ]]; then
    echo "[错误] --source-worktree 与 --source-branch 不匹配。" >&2
    exit 1
  fi
  if [[ -z "$SOURCE_ENTRY_WORKTREE" ]]; then
    if [[ -z "${BRANCH_TO_WORKTREE[$SOURCE_BRANCH]+x}" ]]; then
      echo "[错误] 未找到检出分支 $SOURCE_BRANCH 的 worktree。" >&2
      exit 1
    fi
    SOURCE_ENTRY_BRANCH="$SOURCE_BRANCH"
    SOURCE_ENTRY_WORKTREE="${BRANCH_TO_WORKTREE[$SOURCE_BRANCH]}"
  fi
fi

if [[ -z "$SOURCE_ENTRY_WORKTREE" ]]; then
  echo "[错误] 请通过 --source-worktree 或 --source-branch 指定待合并的 worktree。" >&2
  exit 1
fi

if [[ -z "$SOURCE_ENTRY_BRANCH" ]]; then
  echo "[错误] 源 worktree 没有关联本地分支，无法自动合并。" >&2
  exit 1
fi

if [[ "$SOURCE_ENTRY_BRANCH" == "$TARGET_BRANCH" ]]; then
  echo "[错误] 源分支与目标分支相同，无法执行合并。" >&2
  exit 1
fi

if [[ -z "${BRANCH_TO_WORKTREE[$TARGET_BRANCH]+x}" ]]; then
  echo "[错误] 未找到检出目标分支 $TARGET_BRANCH 的 worktree。" >&2
  exit 1
fi
TARGET_WORKTREE="${BRANCH_TO_WORKTREE[$TARGET_BRANCH]}"

if [[ "$(path_is_inside "$CURRENT_DIR" "$SOURCE_ENTRY_WORKTREE")" == "1" ]]; then
  echo "[错误] 当前目录位于待删除的 worktree 内: $SOURCE_ENTRY_WORKTREE。请切换到主仓库或其它目录后再运行。" >&2
  exit 1
fi

SOURCE_DIRTY="$(git -C "$SOURCE_ENTRY_WORKTREE" status --porcelain --untracked-files=all)"
if [[ -n "$SOURCE_DIRTY" ]]; then
  printf '[错误] 源 worktree 存在未提交改动，无法安全合并。请先提交或暂存:\n%s\n' "$SOURCE_DIRTY" >&2
  exit 1
fi

TARGET_DIRTY="$(git -C "$TARGET_WORKTREE" status --porcelain --untracked-files=all)"
STASH_REF=""
STASH_MESSAGE=""

restore_stash_hint() {
  if [[ -n "$STASH_REF" ]]; then
    log_warn "目标分支原有改动仍保存在 $STASH_REF，如需手动恢复请执行: git -C \"$TARGET_WORKTREE\" stash apply $STASH_REF"
  fi
}

trap restore_stash_hint ERR

if [[ -n "$TARGET_DIRTY" ]]; then
  STASH_MESSAGE="auto-merge-worktree:${SOURCE_ENTRY_BRANCH}->${TARGET_BRANCH}:$(date +%s)"
  log_warn "目标分支 worktree 有未提交改动，准备暂存后再合并: $TARGET_WORKTREE"
  git -C "$TARGET_WORKTREE" stash push --include-untracked -m "$STASH_MESSAGE" >/dev/null
  STASH_REF="$(git -C "$TARGET_WORKTREE" stash list --format='%gd	%s' | awk -F '\t' -v msg="$STASH_MESSAGE" '$2 == msg {print $1; exit}')"
  if [[ -n "$STASH_REF" ]]; then
    log_info "已保存目标分支本地改动: $STASH_REF"
  else
    log_warn "未创建 stash，可能只有文件时间戳变化。继续执行合并。"
  fi
fi

log_info "正在将 $SOURCE_ENTRY_BRANCH 合并到 $TARGET_BRANCH"
git -C "$TARGET_WORKTREE" merge --no-edit "$SOURCE_ENTRY_BRANCH"

log_info "正在删除 worktree: $SOURCE_ENTRY_WORKTREE"
remove_worktree_safely "$REPO_ROOT" "$SOURCE_ENTRY_WORKTREE"
git -C "$REPO_ROOT" worktree prune >/dev/null

if [[ "$DELETE_BRANCH" -eq 1 ]]; then
  log_info "正在删除已合并的本地分支: $SOURCE_ENTRY_BRANCH"
  git -C "$TARGET_WORKTREE" branch -d "$SOURCE_ENTRY_BRANCH"
fi

if [[ -n "$STASH_REF" ]]; then
  log_info "正在恢复目标分支原有未提交改动: $STASH_REF"
  git -C "$TARGET_WORKTREE" stash apply "$STASH_REF" >/dev/null
  git -C "$TARGET_WORKTREE" stash drop "$STASH_REF" >/dev/null
  STASH_REF=""
fi

trap - ERR

printf '\n'
log_info "合并完成: $SOURCE_ENTRY_BRANCH -> $TARGET_BRANCH"
log_info "目标 worktree: $TARGET_WORKTREE"
log_info "已删除 worktree: $SOURCE_ENTRY_WORKTREE"

#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
artifacts_dir="$script_dir/artifacts"
stage_root="$script_dir/stage"
portable_builder="$script_dir/portable-linux/build_portable.py"
front_dir="$repo_root/front"
version_file="$repo_root/VERSION"
package_base_name="orbit-safe-claw"
release_legal_verifier="$repo_root/scripts/verify_release_legal_files.py"
required_release_legal_files=(
  "LICENSE"
  "NOTICE"
  "THIRD_PARTY_NOTICES.md"
  "TRADEMARKS.md"
  "CONTRIBUTING.md"
  "front/dist/THIRD_PARTY_LICENSES.txt"
)

python_bin="${PYTHON:-python3}"
if [[ -z "${PYTHON:-}" && -x "$repo_root/.venv/bin/python" ]]; then
  python_bin="$repo_root/.venv/bin/python"
fi
npm_bin="${NPM:-npm}"

version=""
repository="Augustusjk2008/telegram-cli-bot"
release_branch="master"
release_notes_file=""
mode="BuildAndPublish"
run_checks=0
allow_dirty_worktree=0
auto_confirm_dirty_worktree=0
via_github_actions=0
release_archives=()
linux_portable_archive=""
checksum_archives=()

write_step() {
  printf '[步骤] %s\n' "$1"
}

write_info() {
  printf '[信息] %s\n' "$1"
}

fail() {
  printf '[错误] %s\n' "$1" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
用法:
  .release-local/publish-release.sh --version <version> [options]

选项:
  --version, -Version <version>                 版本号，如 1.0.3 或 v1.0.3
  --repository, -Repository <repo>              GitHub 仓库，默认 Augustusjk2008/telegram-cli-bot
  --release-branch, -ReleaseBranch <branch>     发布分支，默认 master
  --release-notes-file, -ReleaseNotesFile <md>  GitHub Release body 文件
  --mode, -Mode <mode>                          BuildAndPublish | BuildOnly | PublishOnly
  --run-checks, -RunChecks                      运行发布前测试
  --allow-dirty-worktree, -AllowDirtyWorktree   BuildOnly 时允许 tracked dirty
  --auto-confirm-dirty-worktree, -AutoConfirmDirtyWorktree
                                                发布时自动确认提交当前工作区
  --skip-windows-portable, -SkipWindowsPortable 兼容旧命令；本脚本仅打包当前平台
  --via-github-actions                            由 GitHub 的 Linux runner 构建并发布到同一标签
  --help, -h                                    显示帮助
USAGE
}

require_value() {
  local option="$1"
  local value="${2:-}"
  if [[ -z "$value" || "$value" == -* ]]; then
    fail "$option 缺少参数值。"
  fi
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --version=*)
        version="${1#*=}"
        ;;
      --repository=*)
        repository="${1#*=}"
        ;;
      --release-branch=*)
        release_branch="${1#*=}"
        ;;
      --release-notes-file=*)
        release_notes_file="${1#*=}"
        ;;
      --mode=*)
        mode="${1#*=}"
        ;;
      --version|-Version)
        require_value "$1" "${2:-}"
        version="$2"
        shift
        ;;
      --repository|-Repository)
        require_value "$1" "${2:-}"
        repository="$2"
        shift
        ;;
      --release-branch|-ReleaseBranch)
        require_value "$1" "${2:-}"
        release_branch="$2"
        shift
        ;;
      --release-notes-file|-ReleaseNotesFile)
        require_value "$1" "${2:-}"
        release_notes_file="$2"
        shift
        ;;
      --mode|-Mode)
        require_value "$1" "${2:-}"
        mode="$2"
        shift
        ;;
      --run-checks|-RunChecks)
        run_checks=1
        ;;
      --allow-dirty-worktree|-AllowDirtyWorktree)
        allow_dirty_worktree=1
        ;;
      --auto-confirm-dirty-worktree|-AutoConfirmDirtyWorktree)
        auto_confirm_dirty_worktree=1
        ;;
      --skip-windows-portable|-SkipWindowsPortable)
        :
        ;;
      --via-github-actions)
        via_github_actions=1
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        fail "未知参数: $1"
        ;;
    esac
    shift
  done
}

run_checked_command() {
  local working_directory="$1"
  local failure_message="$2"
  shift 2

  set +e
  (cd "$working_directory" && "$@")
  local exit_code=$?
  set -e

  if [[ $exit_code -ne 0 ]]; then
    fail "$failure_message (退出码 $exit_code)"
  fi
}

git_output() {
  local failure_message="$1"
  shift
  local output
  set +e
  output="$(cd "$repo_root" && git "$@" 2>&1)"
  local exit_code=$?
  set -e
  if [[ $exit_code -ne 0 ]]; then
    if [[ -n "$output" ]]; then
      fail "$failure_message: $output"
    fi
    fail "$failure_message"
  fi
  printf '%s\n' "$output"
}

normalize_version() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  if [[ "$value" == v* ]]; then
    value="${value#v}"
  fi
  printf '%s' "$value"
}

assert_valid_version() {
  local value="$1"
  if [[ ! "$value" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$ ]]; then
    fail "版本号格式无效: $value。请使用如 1.0.3 或 1.0.3-beta.1。"
  fi
}

normalize_release_branch() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  if [[ -z "$value" ]]; then
    value="master"
  fi
  printf '%s' "$value"
}

assert_valid_release_branch() {
  local value="$1"
  if [[ -z "$value" || ! "$value" =~ ^[-0-9A-Za-z._/]+$ || "$value" == *..* || "$value" == *//* || "$value" == *@\{* || "$value" == /* || "$value" == */ || "$value" == *. || "$value" == *.lock ]]; then
    fail "发布分支名称无效: $value"
  fi
}

normalize_github_repository() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  value="${value%/}"
  case "$value" in
    https://github.com/*)
      value="${value#https://github.com/}"
      ;;
    ssh://git@github.com/*)
      value="${value#ssh://git@github.com/}"
      ;;
    git@github.com:*)
      value="${value#git@github.com:}"
      ;;
  esac
  value="${value%.git}"
  if [[ ! "$value" =~ ^[0-9A-Za-z_.-]+/[0-9A-Za-z_.-]+$ ]]; then
    fail "GitHub 仓库格式无效: $1"
  fi
  printf '%s' "$value"
}

assert_origin_matches_repository() {
  local expected_repository="$1"
  local fetch_url
  local push_url
  local fetch_repository
  local push_repository

  fetch_url="$(git_output "读取 origin fetch URL 失败" remote get-url origin | head -n 1)"
  push_url="$(git_output "读取 origin push URL 失败" remote get-url --push origin | head -n 1)"
  fetch_repository="$(normalize_github_repository "$fetch_url")"
  push_repository="$(normalize_github_repository "$push_url")"

  if [[ "${fetch_repository,,}" != "${expected_repository,,}" ]]; then
    fail "origin fetch URL 指向 $fetch_repository，但发布仓库为 $expected_repository。"
  fi
  if [[ "${push_repository,,}" != "${expected_repository,,}" ]]; then
    fail "origin push URL 指向 $push_repository，但发布仓库为 $expected_repository。"
  fi
}

get_app_version() {
  if [[ ! -f "$version_file" ]]; then
    fail "未找到版本文件: $version_file"
  fi
  local value
  value="$(tr -d '\r\n' < "$version_file")"
  if [[ -z "${value//[[:space:]]/}" ]]; then
    fail "版本文件为空: $version_file"
  fi
  printf '%s' "$value"
}

set_app_version() {
  local normalized_version="$1"
  printf '%s\n' "$normalized_version" > "$version_file"
}

resolve_release_notes_file() {
  local path_text="$1"
  if [[ -z "${path_text//[[:space:]]/}" ]]; then
    printf '\n'
    return
  fi

  local candidate="$path_text"
  if [[ "$candidate" != /* ]]; then
    candidate="$repo_root/$candidate"
  fi
  if [[ ! -f "$candidate" ]]; then
    fail "未找到 Release Notes 文件: $candidate"
  fi
  realpath "$candidate"
}

get_worktree_status() {
  local tracked_only="${1:-0}"
  local args=(status --short)
  if [[ "$tracked_only" == "1" ]]; then
    args+=(--untracked-files=no)
  fi

  local output
  set +e
  output="$(cd "$repo_root" && git "${args[@]}")"
  local exit_code=$?
  set -e
  if [[ $exit_code -ne 0 ]]; then
    fail "无法读取 git 状态。"
  fi
  printf '%s\n' "$output" | sed '/^[[:space:]]*$/d'
}

assert_release_branch() {
  local expected_branch="$1"
  local expected_repository="$2"
  write_step "校验发布分支 $expected_branch"
  assert_origin_matches_repository "$expected_repository"

  local current_branch
  current_branch="$(git_output "读取当前分支失败" rev-parse --abbrev-ref HEAD | head -n 1)"
  if [[ "$current_branch" == "HEAD" ]]; then
    fail "当前处于 detached HEAD，不能发布。"
  fi
  if [[ "$current_branch" != "$expected_branch" ]]; then
    fail "当前分支为 $current_branch，发布分支必须为 $expected_branch。"
  fi

  local remote_ref="refs/remotes/origin/$expected_branch"
  run_checked_command "$repo_root" "拉取发布分支状态失败" git fetch --tags origin "+refs/heads/$expected_branch:$remote_ref"
  if ! (cd "$repo_root" && git show-ref --verify --quiet "$remote_ref"); then
    fail "未找到远端发布分支 origin/$expected_branch。"
  fi
  if ! (cd "$repo_root" && git merge-base --is-ancestor "origin/$expected_branch" HEAD); then
    fail "当前分支不包含 origin/$expected_branch，请先同步远端发布分支。"
  fi

  write_info "发布分支已校验: $expected_branch"
}

assert_clean_tracked_worktree() {
  local status
  status="$(get_worktree_status 1)"
  if [[ -n "$status" ]]; then
    fail "存在未提交的 tracked 改动，请先提交后再生成本地产物，或显式使用 --allow-dirty-worktree。"
  fi
}

confirm_dirty_worktree_for_publish() {
  local normalized_version="$1"
  shift
  if (($# == 0)); then
    return
  fi

  printf '[警告] 检测到未提交改动，发布时将与版本号一起自动提交当前工作区：\n' >&2
  local line
  for line in "$@"; do
    printf '  %s\n' "$line" >&2
  done

  if [[ "$auto_confirm_dirty_worktree" == "1" ]]; then
    write_info "已启用 --auto-confirm-dirty-worktree，将在发布检查后提交当前工作区并继续发布 $normalized_version。"
    return
  fi

  local answer
  read -r -p "是否在发布检查后提交当前工作区并继续发布 $normalized_version？输入 y 确认: " answer
  if [[ ! "$answer" =~ ^([Yy]|[Yy][Ee][Ss])$ ]]; then
    fail "已取消发布。"
  fi
}

sync_version_file() {
  local normalized_version="$1"
  local current_version
  current_version="$(get_app_version)"
  if [[ "$current_version" == "$normalized_version" ]]; then
    write_info "版本号已是 $normalized_version"
    return
  fi

  write_step "更新版本号到 $normalized_version"
  set_app_version "$normalized_version"
}

invoke_release_prep_checks() {
  write_step "运行后端发布检查"
  run_checked_command "$repo_root" "后端发布检查失败" "$python_bin" -m pytest tests examples/plugins -q

  write_step "运行前端测试门禁"
  run_checked_command "$front_dir" "前端测试门禁失败" "$npm_bin" run test:gate

  write_step "运行前端 lint"
  run_checked_command "$front_dir" "前端 lint 失败" "$npm_bin" run lint
}

invoke_release_front_build() {
  write_step "构建发布包前端"
  (cd "$front_dir" && TCB_FRONT_BUILD_ROOT_BASE=1 "$npm_bin" run build)
}

invoke_front_dist_asset_check() {
  write_step "校验前端构建资源路径"
  run_checked_command "$front_dir" "前端构建资源路径校验失败" node scripts/verify-build-assets.mjs
}

assert_release_legal_files_in_stage() {
  local stage_dir="$1"
  local missing=()
  local relative_path
  for relative_path in "${required_release_legal_files[@]}"; do
    if [[ ! -f "$stage_dir/$relative_path" ]]; then
      missing+=("$relative_path")
    fi
  done
  if ((${#missing[@]} > 0)); then
    fail "发布暂存区缺少必需法律文件（请确认文件已由 Git 跟踪）: ${missing[*]}"
  fi
}

assert_release_archives_contain_legal_files() {
  if [[ ! -f "$release_legal_verifier" ]]; then
    fail "未找到发布归档法律文件校验器: $release_legal_verifier"
  fi
  run_checked_command "$repo_root" "发布归档法律文件校验失败" \
    "$python_bin" "$release_legal_verifier" "${release_archives[@]}"
}

copy_tracked_files_to_stage() {
  local stage_dir="$1"
  write_step "复制 tracked 文件到暂存区"

  while IFS= read -r -d '' relative_path; do
    if [[ -z "$relative_path" ]]; then
      continue
    fi
    local source_path="$repo_root/$relative_path"
    local destination_path="$stage_dir/$relative_path"
    mkdir -p "$(dirname "$destination_path")"
    cp -p "$source_path" "$destination_path"
  done < <(cd "$repo_root" && git ls-files -z -- ':(exclude).web_announcements.json' ':(exclude).web_announcement_reads.json')

  local front_dist="$front_dir/dist"
  if [[ ! -d "$front_dist" ]]; then
    fail "未找到 front/dist，请先完成前端构建。"
  fi

  local front_dist_target="$stage_dir/front/dist"
  rm -rf "$front_dist_target"
  mkdir -p "$(dirname "$front_dist_target")"
  cp -a "$front_dist" "$front_dist_target"

  assert_release_legal_files_in_stage "$stage_dir"
}

new_tar_gz_archive() {
  local source_dir="$1"
  local destination_file="$2"
  local tar_options=()
  if [[ "$(uname -s)" == Linux ]]; then tar_options+=(--hard-dereference); fi
  run_checked_command "$repo_root" "创建 tar.gz 包失败" tar "${tar_options[@]}" -C "$source_dir" -czf "$destination_file.tmp" .
  mv -f "$destination_file.tmp" "$destination_file"
}

new_sha256_file() {
  local path="$1"
  if [[ -z "${path//[[:space:]]/}" || ! -f "$path" ]]; then
    return
  fi

  local hash
  if command -v sha256sum >/dev/null 2>&1; then
    hash="$(sha256sum "$path" | awk '{print tolower($1)}')"
  elif command -v shasum >/dev/null 2>&1; then
    hash="$(shasum -a 256 "$path" | awk '{print tolower($1)}')"
  else
    fail "未找到 sha256sum 或 shasum，无法生成校验文件。"
  fi
  if [[ -z "$hash" ]]; then
    fail "生成校验值失败: $path"
  fi

  local checksum_path="${path}.sha256"
  local filename
  filename="$(basename "$path")"
  printf '%s  %s\n' "$hash" "$filename" > "$checksum_path"
  printf '%s\n' "$checksum_path"
}

new_archive_checksum_files() {
  checksum_archives=()

  local archive
  local checksum
  for archive in "${release_archives[@]}"; do
    checksum="$(new_sha256_file "$archive")"
    if [[ -n "${checksum//[[:space:]]/}" ]]; then
      checksum_archives+=("$checksum")
    fi
  done
}

write_distribution_marker() {
  local root="$1"
  local package_kind="$2"
  local platform="$3"
  local marker_version="$4"
  cat > "$root/.distribution.json" <<JSON
{
  "packageKind": "$package_kind",
  "platform": "$platform",
  "version": "$marker_version",
  "updateProtocol": 1
}
JSON
  run_checked_command "$repo_root" "生成更新清单失败" \
    "$python_bin" "$repo_root/scripts/update_package.py" create --root "$root" --source-root "$repo_root"
}

assert_release_update_payloads() {
  local commit
  commit="$(git_output "读取待发布提交失败" rev-parse HEAD | head -n 1)"
  local arguments=(verify --version "$normalized_version" --commit "$commit" --source-root "$repo_root")
  [[ "$should_publish" == "1" ]] && arguments+=(--require-clean)
  arguments+=("${release_archives[@]}")
  run_checked_command "$repo_root" "发布产物版本、提交或文件完整性校验失败" \
    "$python_bin" "$repo_root/scripts/update_package.py" "${arguments[@]}"
}

set_release_archive_paths() {
  case "$(uname -s)" in
    Linux)
      [[ "$(uname -m)" == x86_64 ]] || fail "Linux 绿色版需要 x86-64 构建机。"
      source_kind="linux"
      source_platform="linux-x64"
      linux_portable_archive="$artifacts_dir/${package_base_name}-linux-x64-portable-${1}.tgz"
      ;;
    Darwin)
      source_kind="macos"
      source_platform="macos-universal"
      ;;
    *) fail "请在 Linux/macOS 使用本脚本，Windows 请使用 publish-release.ps1。" ;;
  esac
  source_archive="$artifacts_dir/${package_base_name}-${source_platform}-${1}.tar.gz"
  release_archives=("$source_archive")
  if [[ -n "$linux_portable_archive" ]]; then release_archives+=("$linux_portable_archive"); fi
}

new_release_archives() (
  local normalized_version="$1" stage_dir
  mkdir -p "$artifacts_dir" "$stage_root"
  stage_dir="$(mktemp -d "$stage_root/${source_platform}-${normalized_version}.XXXXXX")"
  trap 'rm -rf -- "$stage_dir"' EXIT
  copy_tracked_files_to_stage "$stage_dir"
  write_distribution_marker "$stage_dir" "$source_kind" "$source_platform" "$normalized_version"
  new_tar_gz_archive "$stage_dir" "$source_archive"
  if [[ -n "$linux_portable_archive" ]]; then
    write_step "构建 Linux x64 离线绿色版"
    run_checked_command "$repo_root" "打包 Linux 离线运行时失败" "$python_bin" -B "$portable_builder" "$stage_dir" "$script_dir/cache/linux-x64"
    write_distribution_marker "$stage_dir" "linux-portable" "$source_platform" "$normalized_version"
    new_tar_gz_archive "$stage_dir" "$linux_portable_archive"
  fi
)

get_existing_release_archives() {
  local archive
  for archive in "${release_archives[@]}"; do
    [[ -f "$archive" ]] || fail "未找到发布包: $archive"
  done
}

commit_release_changes() {
  local normalized_version="$1"
  local status
  status="$(get_worktree_status 0)"
  if [[ -z "$status" ]]; then
    write_info "工作区无待提交改动，继续沿用当前 HEAD。"
    return
  fi

  write_step "提交发布改动"
  run_checked_command "$repo_root" "暂存发布改动失败" git add -A
  run_checked_command "$repo_root" "提交发布改动失败" git commit -m "chore: release $normalized_version"
}

ensure_tag_at_head() {
  local release_tag="$1"
  local head_commit
  head_commit="$(git_output "读取 HEAD 失败" rev-parse HEAD | head -n 1)"

  set +e
  local existing_tag
  existing_tag="$(cd "$repo_root" && git rev-parse -q --verify "refs/tags/$release_tag" 2>/dev/null)"
  local tag_exit=$?
  set -e
  if [[ $tag_exit -eq 0 && -n "$existing_tag" ]]; then
    local tag_commit
    tag_commit="$(git_output "读取 tag 提交失败" rev-list -n 1 "$release_tag" | head -n 1)"
    if [[ "$tag_commit" != "$head_commit" ]]; then
      fail "tag $release_tag 已存在，但不指向当前 HEAD。"
    fi
    write_info "tag 已存在并指向当前 HEAD: $release_tag"
    return
  fi

  write_step "创建 tag $release_tag"
  if [[ "$via_github_actions" == 1 && -n "$release_notes_path" ]]; then
    { printf 'Release %s\n\n' "$release_tag"; cat "$release_notes_path"; } | git -C "$repo_root" tag -a "$release_tag" HEAD -F -
  else
    run_checked_command "$repo_root" "创建 tag 失败" git tag -a "$release_tag" HEAD -m "Release $release_tag"
  fi
}

get_github_token_from_credential_helper() {
  local output
  set +e
  output="$(printf 'protocol=https\nhost=github.com\n\n' | GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=Never git -c credential.interactive=false credential fill 2>/dev/null)"
  local exit_code=$?
  set -e
  if [[ $exit_code -ne 0 ]]; then
    printf '\n'
    return
  fi

  local line
  while IFS= read -r line; do
    if [[ "$line" == password=* ]]; then
      printf '%s' "${line#password=}"
      return
    fi
  done <<< "$output"
  printf '\n'
}

publish_github_release() {
  local release_tag="$1"
  local repo="$2"
  local release_notes_path="$3"
  local target_branch="$4"

  write_step "推送当前分支到 origin"
  run_checked_command "$repo_root" "推送分支失败" git push origin "HEAD:refs/heads/$target_branch"

  write_step "推送 tag $release_tag 到 origin"
  run_checked_command "$repo_root" "推送 tag 失败" git push origin "refs/tags/$release_tag"

  if [[ "$via_github_actions" == 1 ]]; then
    write_step "提交 Linux 原生发布任务"
    run_checked_command "$repo_root" "提交 GitHub Actions 发布任务失败" git push origin "HEAD:refs/heads/release/linux"
    write_info "GitHub Actions 将从已校验的标签重新构建并上传 Linux 发布包。"
    return
  fi

  local gh_command
  gh_command="$(command -v gh || true)"
  if [[ -z "$gh_command" ]]; then
    fail "未找到 gh 命令，请先安装 GitHub CLI。"
  fi

  if [[ -z "${GH_TOKEN:-}" ]]; then
    local helper_token
    helper_token="$(get_github_token_from_credential_helper)"
    if [[ -n "$helper_token" ]]; then
      export GH_TOKEN="$helper_token"
      write_info "已从 git credential helper 载入 GitHub 凭据。"
    fi
  fi

  local release_assets=("${release_archives[@]}")
  if ((${#checksum_archives[@]} > 0)); then
    release_assets+=("${checksum_archives[@]}")
  fi

  local arguments=(--repo "$repo" --tag "$release_tag")
  if [[ -n "$release_notes_path" ]]; then arguments+=(--notes-file "$release_notes_path"); fi
  run_checked_command "$repo_root" "发布 GitHub Release 失败" "$python_bin" "$script_dir/publish_assets.py" "${arguments[@]}" "${release_assets[@]}"
}

main() {
  parse_args "$@"
  if [[ -z "${version//[[:space:]]/}" ]]; then
    usage
    fail "缺少必填参数 --version。"
  fi
  case "$mode" in
    BuildAndPublish|BuildOnly|PublishOnly)
      ;;
    *)
      fail "Mode 无效: $mode。可选值: BuildAndPublish, BuildOnly, PublishOnly。"
      ;;
  esac

  local normalized_version
  normalized_version="$(normalize_version "$version")"
  assert_valid_version "$normalized_version"
  local normalized_repository
  normalized_repository="$(normalize_github_repository "$repository")"
  local normalized_release_branch
  normalized_release_branch="$(normalize_release_branch "$release_branch")"
  assert_valid_release_branch "$normalized_release_branch"

  if [[ "$via_github_actions" == 1 && ( "$(uname -s)" != Linux || "$mode" == BuildOnly ) ]]; then
    fail "--via-github-actions 仅用于 Linux 的发布模式。"
  fi
  local release_tag="v$normalized_version"
  local should_build=1
  local should_publish=1
  if [[ "$mode" == "PublishOnly" ]]; then
    should_build=0
  fi
  if [[ "$mode" == "BuildOnly" ]]; then
    should_publish=0
  fi

  if [[ "$should_publish" == "1" ]]; then
    assert_release_branch "$normalized_release_branch" "$normalized_repository"
  fi

  write_step "检查工作区状态"
  local worktree_status=()
  if [[ "$should_publish" == "1" ]]; then
    mapfile -t worktree_status < <(get_worktree_status 0)
    if [[ "$should_build" != "1" && ${#worktree_status[@]} -gt 0 ]]; then
      fail "PublishOnly 模式复用现有产物，不支持 dirty worktree；请先提交改动，或使用 BuildAndPublish 重新生成发布包。"
    fi
    confirm_dirty_worktree_for_publish "$normalized_version" "${worktree_status[@]}"
  elif [[ "$allow_dirty_worktree" == "1" ]]; then
    write_info "已允许使用当前未提交改动生成本地产物。"
  else
    assert_clean_tracked_worktree
  fi

  write_step "准备版本 $normalized_version"
  if [[ "$should_build" == "1" ]]; then
    sync_version_file "$normalized_version"
  else
    local current_version
    current_version="$(get_app_version)"
    if [[ "$current_version" != "$normalized_version" ]]; then
      fail "PublishOnly 模式要求 VERSION 当前即为 $normalized_version，当前值为 $current_version。"
    fi
  fi

  set_release_archive_paths "$normalized_version"
  write_info "当前模式: $mode"
  if [[ "$should_build" == "1" ]]; then
    if [[ "$run_checks" == "1" ]]; then
      invoke_release_prep_checks
    else
      write_info "已跳过发布前测试检查。"
    fi

    invoke_release_front_build
    invoke_front_dist_asset_check
  else
    write_info "PublishOnly 模式，复用现有产物。"
  fi

  if [[ "$should_publish" == "1" ]]; then
    local release_notes_path
    release_notes_path="$(resolve_release_notes_file "$release_notes_file")"
    commit_release_changes "$normalized_version"
  fi

  local source_identity
  source_identity="$("$python_bin" "$repo_root/scripts/update_package.py" identity --source-root "$repo_root" --plain)" || fail "无法固定发布源码身份"
  read -r TCB_RELEASE_SOURCE_COMMIT TCB_RELEASE_SOURCE_FINGERPRINT <<< "$source_identity"
  export TCB_RELEASE_SOURCE_COMMIT TCB_RELEASE_SOURCE_FINGERPRINT

  if [[ "$should_build" == "1" ]]; then
    new_release_archives "$normalized_version"
  else
    get_existing_release_archives
  fi
  assert_release_archives_contain_legal_files
  assert_release_update_payloads

  if [[ -n "$linux_portable_archive" ]]; then
    run_checked_command "$repo_root" "Linux 离线包启动校验失败" "$python_bin" -B "$script_dir/portable-linux/smoke.py" "$linux_portable_archive"
  fi
  local archive
  for archive in "${release_archives[@]}"; do
    write_info "发布包: $archive"
  done
  new_archive_checksum_files

  if [[ "$should_publish" == "1" ]]; then
    run_checked_command "$repo_root" "发布前源码身份发生变化" \
      "$python_bin" "$repo_root/scripts/update_package.py" identity --source-root "$repo_root" --verify
    ensure_tag_at_head "$release_tag"
    publish_github_release "$release_tag" "$normalized_repository" "$release_notes_path" "$normalized_release_branch"
  else
    write_info "已跳过 GitHub Release 发布。"
  fi

  printf '[完成] 发布流程结束\n'
}

main "$@"

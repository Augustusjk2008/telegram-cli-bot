#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CHECK_ONLY=0
NON_INTERACTIVE=0
EXAMPLE_PLUGINS_MODE="prompt"
INSTALL_USER_PHASE="${INSTALL_USER_PHASE:-0}"
for arg in "$@"; do
  case "$arg" in
    --check-only) CHECK_ONLY=1 ;;
    --non-interactive) NON_INTERACTIVE=1 ;;
    --install-example-plugins)
      if [[ "$EXAMPLE_PLUGINS_MODE" == "skip" ]]; then
        echo "[错误] --install-example-plugins 和 --skip-example-plugins 不能同时使用" >&2
        exit 2
      fi
      EXAMPLE_PLUGINS_MODE="install"
      ;;
    --skip-example-plugins)
      if [[ "$EXAMPLE_PLUGINS_MODE" == "install" ]]; then
        echo "[错误] --install-example-plugins 和 --skip-example-plugins 不能同时使用" >&2
        exit 2
      fi
      EXAMPLE_PLUGINS_MODE="skip"
      ;;
    *)
      echo "[错误] 不支持的参数: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f requirements.txt || ! -f front/package.json || ! -f .env.example ]]; then
  echo "[错误] 当前目录不是完整项目根目录" >&2
  exit 1
fi

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.npm-global/bin:$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.bun/bin:$PATH"

OS_NAME="$(uname -s 2>/dev/null || printf 'unknown')"
case "$OS_NAME" in
  Linux)
    RUNTIME_PLATFORM="linux"
    ;;
  Darwin)
    RUNTIME_PLATFORM="macos"
    ;;
  *)
    echo "[错误] install.sh 目前只支持 Ubuntu / Debian Linux 和 macOS" >&2
    exit 1
    ;;
esac

if [[ "$RUNTIME_PLATFORM" == "linux" ]]; then
  if [[ ! -f /etc/os-release ]]; then
    echo "[错误] install.sh 目前只支持 Ubuntu / Debian Linux 和 macOS" >&2
    exit 1
  fi

  # shellcheck disable=SC1091
  . /etc/os-release
  if [[ "${ID:-}" != "ubuntu" && "${ID:-}" != "debian" && "${ID_LIKE:-}" != *"debian"* ]]; then
    echo "[错误] Linux 安装目前只支持 Ubuntu / Debian" >&2
    exit 1
  fi
fi

if [[ ${EUID:-0} -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

step() {
  printf '[步骤] %s\n' "$1"
}

info() {
  printf '[信息] %s\n' "$1"
}

warn() {
  printf '[警告] %s\n' "$1"
}

fail() {
  printf '[错误] %s\n' "$1" >&2
}

version_ge() {
  local current="$1"
  local minimum="$2"
  local IFS=.
  local current_core minimum_core current_parts minimum_parts
  current_core="${current%%[-+]*}"
  minimum_core="${minimum%%[-+]*}"
  read -r -a current_parts <<< "$current_core"
  read -r -a minimum_parts <<< "$minimum_core"

  for index in 0 1 2; do
    local current_part="${current_parts[$index]:-0}"
    local minimum_part="${minimum_parts[$index]:-0}"
    current_part="${current_part//[^0-9]/}"
    minimum_part="${minimum_part//[^0-9]/}"
    current_part="${current_part:-0}"
    minimum_part="${minimum_part:-0}"
    if ((10#$current_part > 10#$minimum_part)); then
      return 0
    fi
    if ((10#$current_part < 10#$minimum_part)); then
      return 1
    fi
  done
  return 0
}

generate_token() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY'
import secrets
print(secrets.token_hex(12))
PY
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    python - <<'PY'
import secrets
print(secrets.token_hex(12))
PY
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 12
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    printf '%s-%s\n' "$(date +%s)" "$RANDOM" | shasum -a 256 | awk '{print substr($1, 1, 24)}'
    return 0
  fi
  printf '%s%06d%06d\n' "$(date +%s)" "$RANDOM" "$RANDOM" | cut -c1-24
}

update_env_values() {
  local env_path="$1"
  local cli_type="$2"
  local cli_path="$3"
  local working_dir="$4"
  local token="$5"
  local updater_python

  if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    updater_python="$SCRIPT_DIR/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    updater_python="python3"
  else
    updater_python="python"
  fi

  "$updater_python" - "$env_path" "$cli_type" "$cli_path" "$working_dir" "$token" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
updates = {
    "CLI_TYPE": sys.argv[2],
    "CLI_PATH": sys.argv[3],
    "WORKING_DIR": sys.argv[4],
    "WEB_API_TOKEN": sys.argv[5],
}
lines = env_path.read_text(encoding="utf-8").splitlines()
seen = set()
output = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key in updates and not line.lstrip().startswith("#"):
        output.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        output.append(line)
for key, value in updates.items():
    if key not in seen:
        output.append(f"{key}={value}")
env_path.write_text("\n".join(output) + "\n", encoding="utf-8")
PY
}

detect_tailwind_oxide_binding() {
  local front_dir="$1"
  local node_platform node_arch libc_flavor

  node_platform="$(cd "$front_dir" && node -p "process.platform")"
  node_arch="$(cd "$front_dir" && node -p "process.arch")"
  libc_flavor="gnu"

  if command -v ldd >/dev/null 2>&1 && ldd --version 2>&1 | head -n1 | grep -qi musl; then
    libc_flavor="musl"
  fi

  if [[ "$node_platform" == "darwin" ]]; then
    case "$node_arch" in
      x64)
        printf '@tailwindcss/oxide-darwin-x64\n'
        ;;
      arm64)
        printf '@tailwindcss/oxide-darwin-arm64\n'
        ;;
      *)
        return 1
        ;;
    esac
    return 0
  fi

  if [[ "$node_platform" == "linux" ]]; then
    case "$node_arch" in
      x64)
        printf '@tailwindcss/oxide-linux-x64-%s\n' "$libc_flavor"
        ;;
      arm64)
        printf '@tailwindcss/oxide-linux-arm64-%s\n' "$libc_flavor"
        ;;
      arm)
        if [[ "$libc_flavor" == "gnu" ]]; then
          printf '@tailwindcss/oxide-linux-arm-gnueabihf\n'
          return 0
        fi
        return 1
        ;;
      *)
        return 1
        ;;
    esac
    return 0
  fi

  return 1
}

ensure_tailwind_oxide_binding() {
  local front_dir="$SCRIPT_DIR/front"
  local binding_name oxide_version

  if [[ ! -d "$front_dir/node_modules/@tailwindcss/oxide" ]]; then
    return 0
  fi

  if (cd "$front_dir" && node -e "require('@tailwindcss/oxide')" >/dev/null 2>&1); then
    info "Tailwind oxide 原生绑定正常"
    return 0
  fi

  if ! binding_name="$(detect_tailwind_oxide_binding "$front_dir")"; then
    warn "Tailwind oxide 原生绑定加载失败，当前平台暂不支持自动修复"
    return 0
  fi

  oxide_version="$(cd "$front_dir" && node -p "require('./node_modules/@tailwindcss/oxide/package.json').version")"
  warn "检测到 Tailwind oxide 原生绑定缺失，尝试补装 ${binding_name}@${oxide_version}"
  (cd "$front_dir" && npm install --no-save "${binding_name}@${oxide_version}")

  if (cd "$front_dir" && node -e "require('@tailwindcss/oxide')" >/dev/null 2>&1); then
    info "Tailwind oxide 原生绑定已修复"
    return 0
  fi

  fail "Tailwind oxide 原生绑定修复失败，请删除 front/node_modules 后重试"
  return 1
}

detect_python() {
  if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$SCRIPT_DIR/.venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  return 1
}

select_default_cli_type() {
  local choice prompt

  if [[ "$NON_INTERACTIVE" == "1" ]]; then
    printf 'codex\n'
    return 0
  fi

  prompt="选择默认 CLI：1) codex  2) claude  3) kimi [默认 1] "

  read -r -p "$prompt" choice
  case "$choice" in
    2)
      printf 'claude\n'
      ;;
    3)
      printf 'kimi\n'
      ;;
    *)
      printf 'codex\n'
      ;;
  esac
}

ensure_env_file() {
  local cli_type cli_path token
  if [[ -f .env ]]; then
    info "保留现有 .env"
    return 0
  fi

  cp .env.example .env
  cli_type="$(select_default_cli_type)"
  cli_path="$cli_type"
  token="$(generate_token)"
  update_env_values ".env" "$cli_type" "$cli_path" "$SCRIPT_DIR" "$token"

  info ".env 已根据 .env.example 自动生成"
}

initialize_register_code() {
  local python_bin="$1"
  if [[ "$NON_INTERACTIVE" == "1" ]]; then
    return 0
  fi

  local choice=""
  read -r -p "是否初始化邀请码？[y/N] " choice
  if [[ ! "$choice" =~ ^[Yy]$ ]]; then
    return 0
  fi

  local max_uses="1"
  read -r -p "邀请码可用次数 [默认 1]: " max_uses_input
  if [[ -n "${max_uses_input:-}" ]]; then
    max_uses="$max_uses_input"
  fi
  if [[ ! "$max_uses" =~ ^[0-9]+$ ]] || [[ "$max_uses" -le 0 ]]; then
    fail "邀请码可用次数至少为 1"
    exit 1
  fi

  local invite_json
  invite_json="$(CLI_BRIDGE_USERS_PATH="$SCRIPT_DIR/.web_users.json" \
    CLI_BRIDGE_REGISTER_CODES_PATH="$SCRIPT_DIR/.web_register_codes.json" \
    CLI_BRIDGE_AUTH_SECRET_PATH="$SCRIPT_DIR/.web_auth_secret.json" \
    CLI_BRIDGE_REGISTER_CODE_MAX_USES="$max_uses" \
    "$python_bin" -c 'import json, os; from bot.web.auth_store import WebAuthStore; store = WebAuthStore(os.environ["CLI_BRIDGE_USERS_PATH"], os.environ["CLI_BRIDGE_REGISTER_CODES_PATH"], os.environ["CLI_BRIDGE_AUTH_SECRET_PATH"]); print(json.dumps(store.create_register_code(created_by="install-script", max_uses=int(os.environ["CLI_BRIDGE_REGISTER_CODE_MAX_USES"])), ensure_ascii=False))')"
  info "邀请码: $(printf '%s' "$invite_json" | "$python_bin" -c 'import json,sys; print(json.loads(sys.stdin.read())["code"])')"
}

install_example_plugins() {
  local python_bin="$1"
  local mode="$EXAMPLE_PLUGINS_MODE"

  if [[ "$mode" == "prompt" ]]; then
    if [[ "$NON_INTERACTIVE" == "1" ]]; then
      mode="skip"
    else
      local choice=""
      read -r -p "是否安装 examples 中的示例插件？[y/N] " choice
      if [[ "$choice" =~ ^[Yy]$ ]]; then
        mode="install"
      else
        mode="skip"
      fi
    fi
  fi

  if [[ "$mode" != "install" ]]; then
    info "跳过示例插件安装"
    return 0
  fi

  "$python_bin" -m bot.plugins.installer --repo-root "$SCRIPT_DIR" --all
}

run_install_user_phase() {
  local user_home="${1:-}"
  shift || true
  local user_path="/opt/homebrew/bin:/usr/local/bin"
  if [[ -n "$user_home" ]]; then
    user_path="$user_path:$user_home/.npm-global/bin:$user_home/.local/bin:$user_home/.cargo/bin:$user_home/.bun/bin:$PATH"
  else
    user_path="$user_path:$PATH"
  fi
  exec sudo -u "$SUDO_USER" -H env INSTALL_USER_PHASE=1 PATH="$user_path" bash "$0" "$@"
}

install_linux_system_dependencies() {
  step "安装系统依赖"
  $SUDO apt-get update
  $SUDO apt-get install -y python3 python3-pip python3-venv git curl ca-certificates

  if ! command -v node >/dev/null 2>&1 || ! node --version | grep -Eq '^v(18|[2-9][0-9])\.'; then
    step "安装 Node.js LTS"
    curl -fsSL https://deb.nodesource.com/setup_lts.x | $SUDO -E bash -
    $SUDO apt-get install -y nodejs
  fi
}

install_macos_system_dependencies() {
  local packages=()

  step "检查 macOS 依赖"
  if ! command -v python3 >/dev/null 2>&1; then
    packages+=("python")
  elif ! version_ge "$(python3 --version 2>&1 | awk '{print $2}')" "3.10"; then
    packages+=("python")
  fi
  if ! command -v node >/dev/null 2>&1; then
    packages+=("node")
  elif ! version_ge "$(node --version | sed 's/^v//')" "18"; then
    packages+=("node")
  fi
  if ! command -v git >/dev/null 2>&1; then
    packages+=("git")
  fi

  if [[ "${#packages[@]}" -eq 0 ]]; then
    info "macOS 依赖已满足"
    return 0
  fi

  if ! command -v brew >/dev/null 2>&1; then
    fail "缺少 macOS 依赖: ${packages[*]}。请先安装 Homebrew，再执行: brew install ${packages[*]}"
    exit 1
  fi

  step "通过 Homebrew 安装依赖: ${packages[*]}"
  brew install "${packages[@]}"
}

step "检查 Python 3.10+"
python_bin=""
if python_bin="$(detect_python)"; then
  python_version="$("$python_bin" --version 2>&1 | awk '{print $2}')"
  if version_ge "$python_version" "3.10"; then
    info "已检测到 Python ${python_version}"
  else
    warn "Python 版本过低: ${python_version}，需要 3.10+"
  fi
else
  warn "未检测到 Python"
fi

step "检查 Node.js 18+"
if command -v node >/dev/null 2>&1; then
  node_version="$(node --version | sed 's/^v//')"
  if version_ge "$node_version" "18"; then
    info "已检测到 Node.js ${node_version}"
  else
    warn "Node.js 版本过低: ${node_version}，需要 18+"
  fi
else
  warn "未检测到 Node.js"
fi

step "检查 Git"
if command -v git >/dev/null 2>&1; then
  info "$(git --version)"
else
  warn "未检测到 Git"
fi

step "检查 codex / claude / kimi"
if ! command -v codex >/dev/null 2>&1 && ! command -v claude >/dev/null 2>&1 && ! command -v kimi >/dev/null 2>&1; then
  warn "未检测到 codex / claude / kimi。"
  printf '%s\n' "请先安装 Codex CLI、Claude Code CLI 或 Kimi CLI，并确认 codex --version / claude --version / kimi info 可运行。"
else
  command -v codex >/dev/null 2>&1 && info "已检测到 codex"
  command -v claude >/dev/null 2>&1 && info "已检测到 claude"
  command -v kimi >/dev/null 2>&1 && info "已检测到 kimi"
fi

if [[ "$CHECK_ONLY" == "1" ]]; then
  exit 0
fi

if [[ "$INSTALL_USER_PHASE" != "1" ]]; then
  if [[ "$RUNTIME_PLATFORM" == "macos" && ${EUID:-0} -eq 0 && -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    sudo_home="$(eval echo "~$SUDO_USER" 2>/dev/null || true)"
    if [[ "$sudo_home" == "~$SUDO_USER" ]]; then
      sudo_home=""
    fi
    info "检测到 sudo 启动，切回 ${SUDO_USER} 执行 macOS 安装步骤"
    run_install_user_phase "$sudo_home" "$@"
  fi
  if [[ "$RUNTIME_PLATFORM" == "macos" && ${EUID:-0} -eq 0 ]]; then
    fail "macOS 安装请用普通用户执行 bash install.sh，不要直接用 root"
    exit 1
  fi

  if [[ "$RUNTIME_PLATFORM" == "linux" ]]; then
    install_linux_system_dependencies
  else
    install_macos_system_dependencies
  fi

  if [[ ${EUID:-0} -eq 0 && -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    step "修复项目目录权限"
    chown -R "${SUDO_UID:-$(id -u "$SUDO_USER")}":"${SUDO_GID:-$(id -g "$SUDO_USER")}" "$SCRIPT_DIR"
    info "切回 ${SUDO_USER} 执行项目安装步骤"
    run_install_user_phase "" "$@"
  fi
fi

step "准备 Python 虚拟环境"
if ! python_bin="$(detect_python)"; then
  fail "未检测到 Python 3.10+，请先安装 Python"
  exit 1
fi
python_version="$("$python_bin" --version 2>&1 | awk '{print $2}')"
if ! version_ge "$python_version" "3.10"; then
  fail "Python 版本过低: ${python_version}，需要 3.10+"
  exit 1
fi
"${python_bin:-python3}" -m venv .venv
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
PIP_BIN="$SCRIPT_DIR/.venv/bin/pip"

step "安装后端依赖"
"$PIP_BIN" install --upgrade pip
"$PIP_BIN" install -r requirements.txt

step "安装前端依赖"
(cd front && npm install)
ensure_tailwind_oxide_binding

step "构建前端"
(cd front && npm run build)

step "安装示例插件"
install_example_plugins "$PYTHON_BIN"

step "生成 .env"
ensure_env_file

step "可选初始化邀请码"
initialize_register_code "$PYTHON_BIN"

if [[ -z "${WEB_PUBLIC_URL:-}" && ( -z "${WEB_TUNNEL_MODE:-}" || "${WEB_TUNNEL_MODE:-disabled}" == "disabled" ) ]]; then
  info "如需外网访问，可在 .env 中设置 WEB_TUNNEL_MODE=cloudflare_quick，或配置反向代理后填写 WEB_PUBLIC_URL。"
fi

if [[ "$NON_INTERACTIVE" == "0" ]]; then
  info "安装完成，可使用 ./start.sh 启动。"
fi

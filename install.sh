#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CHECK_ONLY=0
NON_INTERACTIVE=0
for arg in "$@"; do
  case "$arg" in
    --check-only) CHECK_ONLY=1 ;;
    --non-interactive) NON_INTERACTIVE=1 ;;
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

if [[ ! -f /etc/os-release ]]; then
  echo "[错误] install.sh 目前只支持 Ubuntu / Debian" >&2
  exit 1
fi

# shellcheck disable=SC1091
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" && "${ID:-}" != "debian" && "${ID_LIKE:-}" != *"debian"* ]]; then
  echo "[错误] install.sh 目前只支持 Ubuntu / Debian" >&2
  exit 1
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
  dpkg --compare-versions "$current" ge "$minimum"
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

detect_default_cli_type() {
  if command -v codex >/dev/null 2>&1; then
    printf 'codex\n'
    return 0
  fi
  if command -v claude >/dev/null 2>&1; then
    printf 'claude\n'
    return 0
  fi
  printf 'codex\n'
}

ensure_env_file() {
  local cli_type cli_path token
  if [[ -f .env ]]; then
    info "保留现有 .env"
    return 0
  fi

  cp .env.example .env
  cli_type="$(detect_default_cli_type)"
  cli_path="$cli_type"
  token="$(date +%s | sha256sum | cut -c1-24)"

  sed -i "s|^CLI_TYPE=.*$|CLI_TYPE=${cli_type}|" .env
  sed -i "s|^CLI_PATH=.*$|CLI_PATH=${cli_path}|" .env
  sed -i "s|^WORKING_DIR=.*$|WORKING_DIR=${SCRIPT_DIR}|" .env
  sed -i "s|^WEB_API_TOKEN=.*$|WEB_API_TOKEN=${token}|" .env

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

step "检查 codex / claude"
if ! command -v codex >/dev/null 2>&1 && ! command -v claude >/dev/null 2>&1; then
  warn "未检测到 codex / claude。"
  printf '%s\n' "请先安装 Codex CLI 或 Claude Code CLI，并确认 codex --version / claude --version 可运行。"
else
  command -v codex >/dev/null 2>&1 && info "已检测到 codex"
  command -v claude >/dev/null 2>&1 && info "已检测到 claude"
fi

if [[ "$CHECK_ONLY" == "1" ]]; then
  exit 0
fi

step "安装系统依赖"
$SUDO apt-get update
$SUDO apt-get install -y python3 python3-pip python3-venv git curl ca-certificates

if ! command -v node >/dev/null 2>&1 || ! node --version | grep -Eq '^v(18|[2-9][0-9])\.'; then
  step "安装 Node.js LTS"
  curl -fsSL https://deb.nodesource.com/setup_lts.x | $SUDO -E bash -
  $SUDO apt-get install -y nodejs
fi

step "准备 Python 虚拟环境"
python3 -m venv .venv
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
PIP_BIN="$SCRIPT_DIR/.venv/bin/pip"

step "安装后端依赖"
"$PIP_BIN" install --upgrade pip
"$PIP_BIN" install -r requirements.txt

step "安装前端依赖"
(cd front && npm install)

step "构建前端"
(cd front && npm run build)

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

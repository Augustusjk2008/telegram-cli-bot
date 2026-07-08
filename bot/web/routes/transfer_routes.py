"""Transfer bridge aiohttp routes."""

from __future__ import annotations

import json
import os
from typing import Any

from aiohttp import web

from bot.web.api_common import WebApiError
from bot.web.auth_store import CAP_ADMIN_OPS
from bot.web.transfer_service import TransferServiceError

HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LiteLLM 网关</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101418;
      --surface: #171d23;
      --surface-strong: #202832;
      --border: #2b3642;
      --text: #e6edf3;
      --muted: #9aa8b6;
      --accent: #4fb477;
      --accent-strong: #2f9e5d;
      --warn: #e6b450;
      --danger: #e05d5d;
      --info: #5aa9e6;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    .container { width: min(1180px, calc(100vw - 32px)); margin: 0 auto; padding: 28px 0 36px; }
    header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
    h1 { margin: 0; font-size: clamp(1.5rem, 2vw, 2rem); font-weight: 700; }
    h2 { margin: 0 0 16px; font-size: 1rem; font-weight: 650; }
    p { margin: 0; }
    code {
      border: 1px solid var(--border);
      border-radius: 5px;
      background: #0d1117;
      color: #8bd4ff;
      padding: 2px 6px;
      font-family: "SF Mono", Consolas, monospace;
      font-size: 0.85em;
    }
    .muted { color: var(--muted); }
    .subhead { margin-top: 6px; color: var(--muted); font-size: 0.92rem; }
    .grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 0.8fr); gap: 16px; align-items: start; }
    .card { border: 1px solid var(--border); border-radius: 8px; background: var(--surface); padding: 18px; }
    .info { margin-bottom: 16px; border-left: 3px solid var(--info); background: #142333; border-radius: 0 8px 8px 0; padding: 12px 14px; line-height: 1.7; color: #c8d6e3; }
    .form-row { display: grid; gap: 7px; margin-bottom: 12px; }
    label { color: var(--muted); font-size: 0.84rem; }
    input {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: #0d1117;
      color: var(--text);
      padding: 8px 10px;
      font: inherit;
    }
    input[readonly] { color: var(--muted); background: #111820; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
    button, .button {
      min-height: 38px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--surface-strong);
      color: var(--text);
      padding: 8px 12px;
      font: inherit;
      cursor: pointer;
      text-decoration: none;
    }
    button:hover, .button:hover { border-color: #506171; }
    button:disabled { cursor: not-allowed; opacity: 0.6; }
    .primary { border-color: var(--accent-strong); background: var(--accent-strong); color: white; }
    .danger { border-color: #7a3030; background: #542727; color: #ffd7d7; }
    .status-line { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 14px; }
    .badge { display: inline-flex; align-items: center; gap: 8px; border-radius: 999px; border: 1px solid var(--border); padding: 5px 10px; font-size: 0.86rem; font-weight: 650; }
    .badge.running { color: #b8f5cd; border-color: #2a6840; background: #153322; }
    .badge.stopped, .badge.not_configured { color: #ffe5a3; border-color: #765c24; background: #352a14; }
    .badge.error { color: #ffd0d0; border-color: #784044; background: #3a1e22; }
    .pulse { width: 8px; height: 8px; border-radius: 999px; background: currentColor; animation: pulse 1.8s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
    .stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
    .stat { min-width: 0; border: 1px solid var(--border); border-radius: 7px; background: #111820; padding: 10px; }
    .stat-value { overflow: hidden; text-overflow: ellipsis; font-size: 1.25rem; font-weight: 700; white-space: nowrap; }
    .stat-label { color: var(--muted); font-size: 0.78rem; margin-top: 3px; }
    .config-list { margin-top: 16px; border-top: 1px solid var(--border); padding-top: 12px; display: grid; gap: 8px; }
    .config-row { display: flex; justify-content: space-between; gap: 12px; font-size: 0.87rem; }
    .config-row span:last-child { text-align: right; word-break: break-all; font-family: "SF Mono", Consolas, monospace; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 860px; }
    th, td { border-bottom: 1px solid var(--border); padding: 10px 8px; text-align: left; vertical-align: top; font-size: 0.84rem; }
    th { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; font-weight: 650; }
    tr.error-row td { background: rgba(224, 93, 93, 0.08); }
    .endpoint { display: inline-block; border: 1px solid var(--border); border-radius: 5px; padding: 2px 6px; background: #0d1117; font-family: "SF Mono", Consolas, monospace; font-size: 0.78rem; }
    .ok { color: #82e6a1; font-weight: 700; }
    .err { color: #ff9696; font-weight: 700; }
    .toast {
      position: fixed;
      top: 18px;
      right: 18px;
      max-width: min(420px, calc(100vw - 36px));
      transform: translateX(calc(100% + 24px));
      transition: transform 0.2s ease;
      border-radius: 8px;
      padding: 12px 14px;
      background: var(--surface-strong);
      border: 1px solid var(--border);
      box-shadow: 0 12px 30px rgba(0,0,0,0.28);
    }
    .toast.show { transform: translateX(0); }
    .toast.success { border-color: #34764a; }
    .toast.error { border-color: #8a3d3d; }
    .empty { padding: 28px 10px; text-align: center; color: var(--muted); }
    @media (max-width: 820px) {
      header { align-items: flex-start; flex-direction: column; }
      .grid, .stats { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>LiteLLM 网关</h1>
        <p class="subhead">配置 LiteLLM model、上游 provider，查看本地网关状态、统计和最近请求。</p>
      </div>
      <a id="status-link" class="button" href="#" target="_blank" rel="noreferrer">状态 JSON</a>
    </header>

    <div class="info">
      将 Codex 或其他 Responses 客户端的 <code>base_url</code> 指向 <code id="local-url">-</code>。Responses / Chat Completions 协议兼容由 LiteLLM 处理。
    </div>

    <div class="grid">
      <section class="card">
        <h2>配置</h2>
        <div class="form-row">
          <label for="remote-url">上游 API 地址</label>
          <input id="remote-url" autocomplete="off" placeholder="https://api.openai.com/v1">
        </div>
        <div class="form-row">
          <label for="remote-key">上游 API Key</label>
          <input id="remote-key" type="password" autocomplete="new-password" placeholder="留空表示不修改现有 Key">
        </div>
        <div class="form-row">
          <label for="remote-model">LiteLLM model</label>
          <input id="remote-model" autocomplete="off" placeholder="openai/gpt-5">
        </div>
        <div class="form-row">
          <label for="model-alias">模型别名</label>
          <input id="model-alias" autocomplete="off" placeholder="gpt-5">
        </div>
        <div class="form-row">
          <label><input id="drop-params" type="checkbox" checked> drop params</label>
        </div>
        <div class="form-row">
          <label for="local-endpoint">本地端点</label>
          <input id="local-endpoint" readonly value="-">
        </div>
        <div class="actions">
          <button id="save-btn" class="primary" type="button">保存配置</button>
          <button id="health-btn" type="button">健康检查</button>
          <button id="clear-key-btn" type="button">清除 Key</button>
        </div>
        <div class="config-list">
          <div class="config-row"><span class="muted">上游地址</span><span id="cfg-remote-url">-</span></div>
          <div class="config-row"><span class="muted">LiteLLM model</span><span id="cfg-remote-model">-</span></div>
          <div class="config-row"><span class="muted">模型别名</span><span id="cfg-model-alias">-</span></div>
          <div class="config-row"><span class="muted">Key 状态</span><span id="cfg-key">-</span></div>
          <div class="config-row"><span class="muted">本地 host / port</span><span id="cfg-local">-</span></div>
        </div>
      </section>

      <section class="card">
        <h2>运行状态</h2>
        <div class="status-line">
          <span id="status-badge" class="badge not_configured">未配置</span>
          <span id="uptime" class="muted">运行时间: 0s</span>
        </div>
        <div class="stats">
          <div class="stat"><div id="stat-req" class="stat-value">0</div><div class="stat-label">总请求</div></div>
          <div class="stat"><div id="stat-in" class="stat-value">0</div><div class="stat-label">流入 KB</div></div>
          <div class="stat"><div id="stat-out" class="stat-value">0</div><div class="stat-label">流出 KB</div></div>
          <div class="stat"><div id="stat-tokens-in" class="stat-value">0</div><div class="stat-label">输入 Tokens</div></div>
          <div class="stat"><div id="stat-tokens-out" class="stat-value">0</div><div class="stat-label">输出 Tokens</div></div>
          <div class="stat"><div id="stat-traffic" class="stat-value">0</div><div class="stat-label">最近请求</div></div>
        </div>
        <div class="actions">
          <button id="reset-btn" class="danger" type="button">重置统计</button>
        </div>
        <p id="last-error" class="muted" style="margin-top:12px;"></p>
      </section>
    </div>

    <section class="card" style="margin-top:16px;">
      <h2>实时流量</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>方法</th>
              <th>端点</th>
              <th>状态</th>
              <th>流入</th>
              <th>流出</th>
              <th>耗时</th>
              <th>模型</th>
              <th>错误提示</th>
            </tr>
          </thead>
          <tbody id="traffic-body">
            <tr><td colspan="9" class="empty">暂无流量记录</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>

  <div id="toast" class="toast" role="status" aria-live="polite"></div>

  <script>
    const $ = (id) => document.getElementById(id);
    const BASE_PATH = (() => {
      const marker = "/api/transfer/page";
      const path = window.location.pathname || "";
      return path.endsWith(marker) ? path.slice(0, -marker.length) : "";
    })();
    const routePath = (path) => `${BASE_PATH}${path}`;
    let toastTimer = null;

    function showToast(message, type = "success") {
      const toast = $("toast");
      toast.textContent = message;
      toast.className = `toast ${type} show`;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
    }

    async function parseJsonResponse(response) {
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.ok === false) {
        const message = payload.error?.message || `请求失败 (${response.status})`;
        throw new Error(message);
      }
      return payload.data || payload;
    }

    function formatBytes(bytes) {
      const value = Number(bytes || 0);
      if (value < 1024) return `${value} B`;
      return `${(value / 1024).toFixed(1)} KB`;
    }

    function formatDuration(ms) {
      const value = Number(ms || 0);
      return value < 1000 ? `${value.toFixed(0)}ms` : `${(value / 1000).toFixed(1)}s`;
    }

    function formatUptime(seconds) {
      const total = Math.max(0, Number(seconds || 0));
      const hours = Math.floor(total / 3600);
      const mins = Math.floor((total % 3600) / 60);
      const secs = Math.floor(total % 60);
      if (hours) return `${hours}h ${mins}m ${secs}s`;
      if (mins) return `${mins}m ${secs}s`;
      return `${secs}s`;
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[ch]));
    }

    function statusLabel(status) {
      if (status === "running") return "运行中";
      if (status === "stopped") return "已停止";
      if (status === "error") return "异常";
      if (status === "not_configured") return "未配置";
      return "未知";
    }

    function updateStatus(data) {
      $("local-url").textContent = data.local_endpoint || data.local_url || "-";
      $("local-endpoint").value = data.local_endpoint || data.local_url || "-";
      $("remote-url").value = data.provider_base_url || "";
      $("remote-model").value = data.litellm_model || "";
      $("model-alias").value = data.model_alias || "";
      $("drop-params").checked = data.drop_params !== false;
      $("cfg-remote-url").textContent = data.provider_base_url || "-";
      $("cfg-remote-model").textContent = data.litellm_model || "-";
      $("cfg-model-alias").textContent = data.model_alias || "-";
      $("cfg-key").textContent = data.provider_api_key_set ? "已设置" : "未设置";
      $("cfg-local").textContent = `${data.local_host || "-"}:${data.local_port || "-"}`;

      const badge = $("status-badge");
      badge.className = `badge ${data.status || "unknown"}`;
      badge.innerHTML = data.status === "running" ? `<span class="pulse"></span>${statusLabel(data.status)}` : statusLabel(data.status);
      $("uptime").textContent = `运行时间: ${formatUptime(data.uptime_seconds)}`;
      $("stat-req").textContent = Number(data.request_count || 0).toLocaleString();
      $("stat-in").textContent = formatBytes(data.total_bytes_in);
      $("stat-out").textContent = formatBytes(data.total_bytes_out);
      $("stat-tokens-in").textContent = Number(data.total_input_tokens || 0).toLocaleString();
      $("stat-tokens-out").textContent = Number(data.total_output_tokens || 0).toLocaleString();
      $("stat-traffic").textContent = Number((data.recent_traffic || []).length).toLocaleString();
      $("last-error").textContent = data.last_error ? `最近错误: ${data.last_error}` : "";
      renderTraffic(data.recent_traffic || []);
    }

    function renderTraffic(records) {
      const body = $("traffic-body");
      if (!records.length) {
        body.innerHTML = '<tr><td colspan="9" class="empty">暂无流量记录</td></tr>';
        return;
      }
      body.innerHTML = records.slice().reverse().map((record) => {
        const failed = Number(record.status || 0) >= 400 || record.error;
        return `<tr class="${failed ? "error-row" : ""}">
          <td>${escapeHtml(record.timestamp)}</td>
          <td>${escapeHtml(record.method || "-")}</td>
          <td><span class="endpoint">${escapeHtml(record.endpoint || "-")}</span></td>
          <td class="${failed ? "err" : "ok"}">${escapeHtml(record.status || "-")}</td>
          <td>${formatBytes(record.bytes_in)}</td>
          <td>${formatBytes(record.bytes_out)}</td>
          <td>${formatDuration(record.duration_ms)}</td>
          <td>${escapeHtml(record.model || "-")}</td>
          <td title="${escapeHtml(record.error || "")}">${escapeHtml(record.error || "-")}</td>
        </tr>`;
      }).join("");
    }

    async function refreshStatus({ quiet = false } = {}) {
      try {
        const data = await parseJsonResponse(await fetch(routePath("/api/transfer/status"), { cache: "no-store" }));
        updateStatus(data);
      } catch (error) {
        $("status-badge").className = "badge error";
        $("status-badge").textContent = "异常";
        if (!quiet) showToast(error.message, "error");
      }
    }

    async function saveConfig(clearKey = false) {
      const body = {
        provider_base_url: $("remote-url").value.trim(),
        litellm_model: $("remote-model").value.trim(),
        model_alias: $("model-alias").value.trim(),
        drop_params: $("drop-params").checked,
      };
      const key = $("remote-key").value;
      if (clearKey) {
        body.clear_provider_api_key = true;
      } else if (key) {
        body.provider_api_key = key;
      }
      $("save-btn").disabled = true;
      try {
        const data = await parseJsonResponse(await fetch(routePath("/api/admin/transfer/config"), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }));
        $("remote-key").value = "";
        updateStatus(data);
        showToast(data.restart_required ? "配置已保存，本地端点调整需重启生效" : "配置已保存");
      } catch (error) {
        showToast(error.message, "error");
      } finally {
        $("save-btn").disabled = false;
      }
    }

    async function testConnection() {
      const started = performance.now();
      try {
        const data = await parseJsonResponse(await fetch(routePath("/api/transfer/health"), { cache: "no-store" }));
        showToast(`健康检查正常，状态: ${data.status || "unknown"}，耗时 ${Math.round(performance.now() - started)}ms`);
      } catch (error) {
        showToast(error.message, "error");
      }
    }

    async function resetStats() {
      if (!confirm("确定要重置桥接统计和最近流量记录吗？")) return;
      try {
        const data = await parseJsonResponse(await fetch(routePath("/api/admin/transfer/reset"), { method: "POST" }));
        updateStatus(data);
        showToast("统计已重置");
      } catch (error) {
        showToast(error.message, "error");
      }
    }

    $("status-link").href = routePath("/api/transfer/status");
    $("save-btn").addEventListener("click", () => saveConfig(false));
    $("clear-key-btn").addEventListener("click", () => saveConfig(true));
    $("health-btn").addEventListener("click", testConnection);
    $("reset-btn").addEventListener("click", resetStats);

    refreshStatus();
    setInterval(() => refreshStatus({ quiet: true }), 2000);
  </script>
</body>
</html>
"""


def _json(data: dict[str, Any], status: int = 200) -> web.Response:
    response = web.json_response(data, status=status, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))
    response.enable_compression()
    return response


def _server(request: web.Request):
    return request.app["server"]


def _is_loopback_value(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in {"127.0.0.1", "::1", "localhost"} or text.startswith("127.")


def _is_loopback_request(request: web.Request) -> bool:
    if any(str(request.headers.get(name, "")).strip() for name in ("Forwarded", "X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP", "True-Client-IP")):
        return False
    host = str(request.headers.get("Host", "")).split(":", 1)[0].strip()
    if host and not _is_loopback_value(host):
        return False
    if _is_loopback_value(request.remote):
        return True
    transport = request.transport
    if transport is None:
        return False
    peername = transport.get_extra_info("peername")
    if isinstance(peername, tuple) and peername:
        return _is_loopback_value(peername[0])
    return _is_loopback_value(peername)


def _require_transfer_access(request: web.Request) -> None:
    expected = os.environ.get("TRANSFER_ACCESS_TOKEN", "").strip()
    if expected:
        actual = request.headers.get("X-TCB-Transfer-Token", "").strip()
        if actual != expected:
            raise WebApiError(401, "transfer_unauthorized", "Transfer token 无效")
        return
    if not _is_loopback_request(request):
        raise WebApiError(403, "transfer_loopback_required", "Transfer bridge 默认仅允许本机访问")


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise WebApiError(400, "invalid_json", "请求体不是合法 JSON") from exc
    if not isinstance(body, dict):
        raise WebApiError(400, "invalid_json", "请求体必须是 JSON 对象")
    return body


def _transfer_error(exc: TransferServiceError) -> WebApiError:
    return WebApiError(exc.status, exc.code, exc.message)


def _json_or_raw_response(result) -> web.Response:
    if result.raw_body is not None:
        return web.Response(
            body=result.raw_body,
            status=result.status,
            headers=result.headers,
            content_type=result.content_type,
        )
    return _json(result.data or {}, status=result.status)


async def create_response(request: web.Request) -> web.StreamResponse | web.Response:
    _require_transfer_access(request)
    server = _server(request)
    try:
        result = await server.transfer_service.create_response(await _read_json(request))
    except TransferServiceError as exc:
        raise _transfer_error(exc) from exc
    if result.stream is None:
        return _json_or_raw_response(result)
    response = web.StreamResponse(status=result.status, headers=result.headers)
    response.content_type = result.content_type or "text/event-stream"
    await response.prepare(request)
    async for chunk in result.stream:
        await response.write(chunk)
    await response.write_eof()
    return response


async def proxy_chat_completions(request: web.Request) -> web.StreamResponse | web.Response:
    _require_transfer_access(request)
    server = _server(request)
    try:
        result = await server.transfer_service.proxy_chat_completions(await _read_json(request))
    except TransferServiceError as exc:
        raise _transfer_error(exc) from exc
    if result.stream is not None:
        response = web.StreamResponse(status=result.status, headers=result.headers)
        response.content_type = result.content_type or "text/event-stream"
        await response.prepare(request)
        async for chunk in result.stream:
            await response.write(chunk)
        await response.write_eof()
        return response
    return _json_or_raw_response(result)


async def get_response(request: web.Request) -> web.Response:
    _require_transfer_access(request)
    response_id = str(request.match_info.get("response_id") or "")
    server = _server(request)
    try:
        result = await server.transfer_service.get_response(response_id)
    except TransferServiceError as exc:
        raise _transfer_error(exc) from exc
    return _json_or_raw_response(result)


async def delete_response(request: web.Request) -> web.Response:
    _require_transfer_access(request)
    response_id = str(request.match_info.get("response_id") or "")
    server = _server(request)
    try:
        result = await server.transfer_service.delete_response(response_id)
    except TransferServiceError as exc:
        raise _transfer_error(exc) from exc
    return _json_or_raw_response(result)


async def health(request: web.Request) -> web.Response:
    service = _server(request).transfer_service
    status_data = service.get_status()
    return _json(
        {
            "ok": True,
            "data": {
                "status": status_data["status"],
                "enabled": service.config.enabled,
                "litellm_running": status_data["litellm_running"],
            },
        }
    )


async def status(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_auth(request)
    return _json({"ok": True, "data": server.transfer_service.get_status(base_path=server._web_base_path())})


async def admin_status(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    return _json({"ok": True, "data": server.transfer_service.get_status(base_path=server._web_base_path())})


async def page(request: web.Request) -> web.Response:
    return web.Response(text=HTML_PAGE, content_type="text/html")


async def reset(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    server.transfer_service.reset_stats()
    return _json({"ok": True, "data": server.transfer_service.get_status(base_path=server._web_base_path())})


async def config(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    try:
        data = server.transfer_service.update_config(await _read_json(request))
    except TransferServiceError as exc:
        raise _transfer_error(exc) from exc
    status_data = server.transfer_service.get_status(base_path=server._web_base_path())
    if data.get("restart_required"):
        status_data["restart_required"] = data.get("restart_required")
        status_data["restart_required_reason"] = data.get("restart_required_reason", "")
    return _json({"ok": True, "data": status_data})


def register(app: web.Application, server) -> None:
    app["server"] = server
    app.router.add_post("/v1/responses", create_response)
    app.router.add_post("/responses", create_response)
    app.router.add_get("/v1/responses/{response_id}", get_response)
    app.router.add_get("/responses/{response_id}", get_response)
    app.router.add_delete("/v1/responses/{response_id}", delete_response)
    app.router.add_delete("/responses/{response_id}", delete_response)
    app.router.add_post("/v1/chat/completions", proxy_chat_completions)
    app.router.add_post("/chat/completions", proxy_chat_completions)
    app.router.add_get("/api/transfer/health", health)
    app.router.add_get("/api/transfer/status", status)
    app.router.add_get("/api/admin/transfer/status", admin_status)
    app.router.add_get("/api/transfer/page", page)
    app.router.add_post("/api/admin/transfer/reset", reset)
    app.router.add_patch("/api/admin/transfer/config", config)

"""Codex app-server adapter (protocol baseline: codex-cli 0.159.2).

Parameter mapping, after the caller's allow_unsafe_cli clamp/filter:
  Independent params_config.codex_server -> existing Codex argument builder.
  model / --model / -c model -> thread model and turn/start.model every turn.
  reasoning_effort / -c model_reasoning_effort -> turn/start.effort every turn.
  cwd / --cd -> subprocess cwd and thread cwd; --sandbox -> thread sandbox.
  yolo -> never + danger-full-access; --full-auto -> on-request + workspace-write.
  --approval-policy / --ask-for-approval -> thread approvalPolicy.
  -c / --config (including MCP), --enable/disable, --search -> process config.
  --add-dir -> sandbox_workspace_write.writable_roots; --image -> localImage input.
  --output-schema -> turn outputSchema; --ephemeral -> thread/start.ephemeral.
  --json / json_output and --color -> structured transport, without terminal color.
  skip_git_check=false -> check Git before opening; app-server itself needs no check.

Unknown/exec-only extra arguments (including --output-last-message, --profile,
--oss, --local-provider, --timeout, review/resume positional commands) fail explicitly.
No exec fallback; project Plan prompts never select native collaboration/Plan Mode.
Non-interactive requests decline approvals/elicitation, grant no permissions, and
return empty user answers. A filtered yolo setting never permits later escalation.
Models/effort update each turn; startup config/env/CODEX_HOME/cwd/MCP changes rebuild.
Use close_owner/close_bot/aclose asynchronously, or release_owner/release_bot from
synchronous lifecycle hooks. The latter schedule on the runtime's owning loop.
"""

from .client import CodexServerError
from .runtime import (
    CodexServerRuntime, CodexServerRuntimeRequest, get_codex_server_registry,
    release_bot, release_owner,
)

__all__ = ["CodexServerError", "CodexServerRuntime", "CodexServerRuntimeRequest", "get_codex_server_registry", "release_owner", "release_bot"]

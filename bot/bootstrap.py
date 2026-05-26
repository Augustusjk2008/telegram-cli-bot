from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DEFAULT_NOFILE_TARGET = 8192


def ensure_nofile_limit(target: int = _DEFAULT_NOFILE_TARGET) -> None:
    """Best-effort raise of the per-process open file descriptor soft limit."""
    try:
        import resource
    except ImportError:
        return

    try:
        soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (OSError, ValueError):
        return

    desired_limit = max(int(target), int(soft_limit or 0))
    if hard_limit not in (-1, resource.RLIM_INFINITY):
        desired_limit = min(desired_limit, int(hard_limit))

    if desired_limit <= soft_limit:
        return

    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (desired_limit, hard_limit))
    except (OSError, ValueError) as exc:
        logger.warning(
            "提升文件句柄上限失败: soft=%s hard=%s target=%s error=%s",
            soft_limit,
            hard_limit,
            desired_limit,
            exc,
        )

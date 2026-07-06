"""Small OpenAI-compatible HTTP client shared by web services."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientResponse, ClientSession, ClientTimeout


class OpenAICompatibleClientError(Exception):
    def __init__(self, status: int, message: str, *, code: str = "openai_compatible_error") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def build_openai_compatible_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


class OpenAICompatibleClient:
    def __init__(self, session: ClientSession | None = None) -> None:
        self._session = session
        self._owns_session = session is None

    async def close(self) -> None:
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()

    async def _get_session(self, timeout_seconds: float | None = None) -> ClientSession:
        if self._session is None or self._session.closed:
            timeout = ClientTimeout(total=timeout_seconds) if timeout_seconds else ClientTimeout(total=300)
            self._session = ClientSession(timeout=timeout)
            self._owns_session = True
        return self._session

    async def post_json(
        self,
        *,
        url: str,
        api_key: str,
        body: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session(timeout_seconds)
        request_kwargs: dict[str, Any] = {
            "json": body,
            "headers": build_openai_compatible_headers(api_key),
        }
        if timeout_seconds:
            request_kwargs["timeout"] = ClientTimeout(total=timeout_seconds)
        async with session.post(url, **request_kwargs) as response:
            await self.raise_for_status(response)
            data = await response.json(content_type=None)
            if not isinstance(data, dict):
                raise OpenAICompatibleClientError(502, "Remote API returned non-object JSON", code="invalid_remote_response")
            return data

    async def post_chat_completion(
        self,
        *,
        base_url: str,
        api_key: str,
        body: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await self.post_json(
            url=f"{base_url.rstrip('/')}/chat/completions",
            api_key=api_key,
            body=body,
            timeout_seconds=timeout_seconds,
        )

    async def raise_for_status(self, response: ClientResponse) -> None:
        if response.status < 400:
            return
        text = await response.text()
        raise OpenAICompatibleClientError(response.status, f"Remote API error: {text[:500]}", code="remote_api_error")

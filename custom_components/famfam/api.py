"""HTTP client for the FamFam Home Assistant API.

Vendored in the integration — there is no separate PyPI library. All calls go
through the famfam.life proxy (or a configured base URL) under /api/v1/ha.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import aiohttp

from .const import DEFAULT_BASE_URL

_LOGGER = logging.getLogger(__name__)

API_PREFIX = "/api/v1/ha"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class FamFamApiError(Exception):
    """An error response from the FamFam API."""

    def __init__(
        self, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        """Initialise from the API's {error: {code, message, details?}} shape."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class FamFamAuthError(FamFamApiError):
    """The token was rejected (invalid or revoked)."""


class FamFamConnectionError(FamFamApiError):
    """The FamFam API could not be reached."""


@dataclass(slots=True)
class StateResult:
    """Result of a conditional GET /state."""

    changed: bool
    payload: dict[str, Any] | None
    etag: str | None


class FamFamApiClient:
    """Minimal async client for the FamFam Home Assistant API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        """Initialise with an injected session; the client never creates one."""
        self._session = session
        self._token = token
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> aiohttp.ClientResponse:
        # The token must never appear in logs at any level.
        headers = {"Authorization": f"Bearer {self._token}"}
        if extra_headers:
            headers.update(extra_headers)
        _LOGGER.debug("%s %s%s", method, API_PREFIX, path)
        try:
            response = await self._session.request(
                method,
                f"{self._base_url}{API_PREFIX}{path}",
                json=json,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise FamFamConnectionError(
                "cannot_connect", f"Error connecting to FamFam: {err}"
            ) from err
        if response.status < 400:
            return response
        code, message, details = await self._parse_error(response)
        if response.status == 401:
            raise FamFamAuthError(code, message, details)
        if response.status == 429:
            raise FamFamApiError("rate_limited", message, details)
        if response.status >= 500:
            raise FamFamConnectionError(code, message, details)
        raise FamFamApiError(code, message, details)

    @staticmethod
    async def _parse_error(
        response: aiohttp.ClientResponse,
    ) -> tuple[str, str, dict[str, Any] | None]:
        try:
            body = await response.json()
            error = body["error"]
            return (
                str(error["code"]),
                str(error.get("message", "")),
                error.get("details"),
            )
        except (aiohttp.ClientError, LookupError, TypeError, ValueError):
            return "unknown", f"HTTP {response.status}", None

    async def async_bootstrap(self) -> dict[str, Any]:
        """Fetch the family shape (GET /bootstrap)."""
        response = await self._request("GET", "/bootstrap")
        return await response.json()

    async def async_get_state(self, etag: str | None) -> StateResult:
        """Conditionally fetch the full state (GET /state).

        A 304 means the payload is unchanged since the given ETag.
        """
        headers = {"If-None-Match": etag} if etag else None
        response = await self._request("GET", "/state", extra_headers=headers)
        if response.status == 304:
            return StateResult(changed=False, payload=None, etag=etag)
        return StateResult(
            changed=True,
            payload=await response.json(),
            etag=response.headers.get("ETag"),
        )

    async def async_create_item(
        self, list_id: str, text: str, category: str | None = None
    ) -> None:
        """Add an item to a list."""
        body: dict[str, Any] = {"text": text}
        if category is not None:
            body["category"] = category
        await self._request("POST", f"/lists/{list_id}/items", json=body)

    async def async_update_item(
        self, list_id: str, item_id: str, changes: dict[str, Any]
    ) -> None:
        """PATCH an item with exactly the given changes.

        The caller diffs against the current item first — fields the user
        didn't change are never sent, so the server preserves category,
        addedBy, checkedBy and createdAt (spec §5.1 data-loss guard).
        """
        await self._request(
            "PATCH", f"/lists/{list_id}/items/{item_id}", json=changes
        )

    async def async_delete_item(self, list_id: str, item_id: str) -> None:
        """Delete an item from a list."""
        await self._request("DELETE", f"/lists/{list_id}/items/{item_id}")

    async def async_create_event(self, body: dict[str, Any]) -> None:
        """Create a calendar event."""
        await self._request("POST", "/events", json=body)

    async def async_update_event(
        self, event_id: str, changes: dict[str, Any]
    ) -> None:
        """PATCH an event with exactly the given changes.

        Server semantics: an absent key is untouched, null clears the field.
        The caller diffs first and must send the master id — the server
        rejects synthetic "{masterId}::{date}" occurrence ids.
        """
        await self._request("PATCH", f"/events/{event_id}", json=changes)

    async def async_delete_event(self, event_id: str) -> None:
        """Delete an event (the whole series for repeating events)."""
        await self._request("DELETE", f"/events/{event_id}")

    async def async_start_trip(self, request_id: str) -> None:
        """Announce a shopping trip (POST /trips).

        The server attributes the trip to the token's acting member and
        applies its default window; requestId dedupes transport retries.
        Plus-gated: a free family gets a 403 with code "plus_required".
        """
        await self._request("POST", "/trips", json={"requestId": request_id})

    async def async_search_recipes(self, query: str) -> list[dict[str, Any]]:
        """Search the family's recipes (GET /recipes/search).

        Substring match on name and ingredients over the newest 500 recipes,
        capped at 50 results.
        """
        response = await self._request(
            "GET", "/recipes/search", params={"q": query}
        )
        payload = await response.json()
        return payload.get("recipes", [])

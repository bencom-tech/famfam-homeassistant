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


@dataclass(slots=True)
class _Response:
    """A successful (< 400) response, already read and released."""

    status: int
    etag: str | None
    payload: dict[str, Any] | None


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
        read_body: bool = True,
    ) -> _Response:
        """Make a request and release the connection before returning.

        The body is consumed inside the context manager so the connection goes
        straight back to Home Assistant's shared session pool. Writes whose
        body nobody reads would otherwise hold it until garbage collection and
        cost a fresh TLS handshake on the next poll.
        """
        # The token must never appear in logs at any level.
        headers = {"Authorization": f"Bearer {self._token}"}
        if extra_headers:
            headers.update(extra_headers)
        _LOGGER.debug("%s %s%s", method, API_PREFIX, path)
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{API_PREFIX}{path}",
                json=json,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                status = response.status
                if status < 400:
                    payload = None
                    if read_body and status != 304:
                        payload = await self._parse_json(response)
                    return _Response(status, response.headers.get("ETag"), payload)
                code, message, details = await self._parse_error(response)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise FamFamConnectionError(
                "cannot_connect", f"Error connecting to FamFam: {err}"
            ) from err
        if status == 401:
            raise FamFamAuthError(code, message, details)
        if status == 429:
            raise FamFamApiError("rate_limited", message, details)
        if status >= 500:
            raise FamFamConnectionError(code, message, details)
        raise FamFamApiError(code, message, details)

    @staticmethod
    async def _parse_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
        """The JSON object body, or an invalid_response error."""
        try:
            payload = await response.json()
        except (aiohttp.ContentTypeError, ValueError) as err:
            raise FamFamApiError(
                "invalid_response", f"FamFam returned a non-JSON response: {err}"
            ) from err
        if not isinstance(payload, dict):
            raise FamFamApiError(
                "invalid_response", "FamFam returned an unexpected response body"
            )
        return payload

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
        assert response.payload is not None
        return response.payload

    async def async_get_state(self, etag: str | None) -> StateResult:
        """Conditionally fetch the full state (GET /state).

        A 304 means the payload is unchanged since the given ETag.
        """
        headers = {"If-None-Match": etag} if etag else None
        response = await self._request("GET", "/state", extra_headers=headers)
        if response.status == 304:
            return StateResult(changed=False, payload=None, etag=etag)
        return StateResult(
            changed=True, payload=response.payload, etag=response.etag
        )

    async def async_create_item(
        self, list_id: str, text: str, category: str | None = None
    ) -> None:
        """Add an item to a list."""
        body: dict[str, Any] = {"text": text}
        if category is not None:
            body["category"] = category
        await self._request(
            "POST", f"/lists/{list_id}/items", json=body, read_body=False
        )

    async def async_update_item(
        self, list_id: str, item_id: str, changes: dict[str, Any]
    ) -> None:
        """PATCH an item with exactly the given changes.

        The caller diffs against the current item first — fields the user
        didn't change are never sent, so the server preserves category,
        addedBy, checkedBy and createdAt (spec §5.1 data-loss guard).
        """
        await self._request(
            "PATCH",
            f"/lists/{list_id}/items/{item_id}",
            json=changes,
            read_body=False,
        )

    async def async_delete_item(self, list_id: str, item_id: str) -> None:
        """Delete an item from a list."""
        await self._request(
            "DELETE", f"/lists/{list_id}/items/{item_id}", read_body=False
        )

    async def async_create_event(self, body: dict[str, Any]) -> None:
        """Create a calendar event."""
        await self._request("POST", "/events", json=body, read_body=False)

    async def async_update_event(
        self, event_id: str, changes: dict[str, Any]
    ) -> None:
        """PATCH an event with exactly the given changes.

        Server semantics: an absent key is untouched, null clears the field.
        The caller diffs first and must send the master id — the server
        rejects synthetic "{masterId}::{date}" occurrence ids.
        """
        await self._request(
            "PATCH", f"/events/{event_id}", json=changes, read_body=False
        )

    async def async_delete_event(self, event_id: str) -> None:
        """Delete an event (the whole series for repeating events)."""
        await self._request("DELETE", f"/events/{event_id}", read_body=False)

    async def async_start_trip(self, request_id: str) -> None:
        """Announce a shopping trip (POST /trips).

        The server attributes the trip to the token's acting member and
        applies its default window; requestId dedupes transport retries.
        Plus-gated: a free family gets a 403 with code "plus_required".
        """
        await self._request(
            "POST", "/trips", json={"requestId": request_id}, read_body=False
        )

    async def async_end_trip(self) -> None:
        """End the current shopping trip (DELETE /trips/current).

        Idempotent — ending when no trip is running is a success. Any member
        may end a trip, not just the one who started it.
        """
        await self._request("DELETE", "/trips/current", read_body=False)

    async def async_set_checkin(
        self, date: str, member_id: str, status: str
    ) -> None:
        """Set one member's dinner check-in (PUT /checkins/{date}/{memberId}).

        status: "eating" | "no-meal" | "no-response". The server stamps the
        answer's source as manual. Answering for another member is
        organiser-only — the token's member gets a 403 "organiser_only".
        """
        await self._request(
            "PUT",
            f"/checkins/{date}/{member_id}",
            json={"status": status},
            read_body=False,
        )

    async def async_set_meal(
        self,
        date: str,
        *,
        recipe_id: str | None = None,
        free_text: str | None = None,
    ) -> None:
        """Set the planned meal for a date (PUT /meals/{date}).

        Exactly one of recipe_id or free_text — the server rejects both or
        neither.
        """
        body: dict[str, Any] = (
            {"recipeId": recipe_id}
            if recipe_id is not None
            else {"freeText": free_text}
        )
        await self._request("PUT", f"/meals/{date}", json=body, read_body=False)

    async def async_add_meal_ingredients_to_list(
        self, date_from: str, date_to: str, list_id: str
    ) -> None:
        """Send planned-meal ingredients to a list (POST /meals/ingredients-to-list).

        The server reuses Shop for Meals' deduplication against every
        existing item. All three fields are required server-side; the range
        is capped at 31 days.
        """
        await self._request(
            "POST",
            "/meals/ingredients-to-list",
            json={"dateFrom": date_from, "dateTo": date_to, "listId": list_id},
            read_body=False,
        )

    async def async_search_recipes(
        self,
        query: str = "",
        *,
        cuisine: str | None = None,
        diet: str | None = None,
        free_from: str | None = None,
        course: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search the family's recipes (GET /recipes/search).

        `q` is a substring match on name and ingredients; the other filters
        match against the family's taxonomy values. All are optional and
        combine — an empty query with filters is a match-all within them.
        Runs over the newest 500 recipes, capped at 50 results.
        """
        params = {"q": query}
        for key, value in (
            ("cuisine", cuisine),
            ("diet", diet),
            ("freeFrom", free_from),
            ("course", course),
        ):
            if value is not None:
                params[key] = value
        response = await self._request("GET", "/recipes/search", params=params)
        recipes = (response.payload or {}).get("recipes", [])
        return recipes if isinstance(recipes, list) else []

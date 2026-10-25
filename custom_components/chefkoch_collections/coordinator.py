"""Fetch Chefkoch cookbook collections + optional week plan."""

from __future__ import annotations

import json as _json
import logging
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_BASE,
    ATTR_HAS_MEAL_PLANNER,
    AUTH_URL,
    CONF_EMAIL,
    CONF_PASSWORD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    IMAGE_FORMAT,
    ME_URL,
    SOURCE_CHEFKOCH,
    WEEKPLAN_ENTRIES_URL,
)

_LOGGER = logging.getLogger(__name__)

_PAGE_SIZE = 100
_MAX_PAGES = 100
_COLLECTION_ID_RE = re.compile(r"^user-[a-f0-9]+-\d+$", re.IGNORECASE)


def _image_url(template: str | None) -> str | None:
    if not template:
        return None
    return template.replace("<format>", IMAGE_FORMAT).replace(
        "\u003cformat\u003e", IMAGE_FORMAT
    )


def _prep_minutes(recipe: dict[str, Any]) -> int | None:
    """Chefkoch preparationTime/totalTime are already minutes."""
    raw = recipe.get("preparationTime")
    if raw in (None, "", 0, "0"):
        raw = recipe.get("totalTime")
    if raw in (None, "", 0, "0"):
        return None
    try:
        minutes = int(float(raw))
    except (TypeError, ValueError):
        return None
    return minutes if minutes > 0 else None


def _normalize_rating(value: Any) -> float | int | None:
    """Round to one decimal; drop empty/zero ratings."""
    if value in (None, "", 0, "0"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    rounded = round(number, 1)
    return int(rounded) if rounded == int(rounded) else rounded


def _rating_fields(recipe: dict[str, Any]) -> tuple[float | int | None, int | None]:
    """Extract FWL-shaped rating + vote count from Chefkoch recipe JSON."""
    raw = recipe.get("rating")
    rating_raw: Any = None
    count_raw: Any = None
    if isinstance(raw, dict):
        rating_raw = raw.get("rating")
        count_raw = raw.get("numVotes")
    else:
        rating_raw = raw
        count_raw = recipe.get("numVotes") or recipe.get("rating_count")
    rating = _normalize_rating(rating_raw)
    count: int | None = None
    if count_raw not in (None, ""):
        try:
            parsed = int(float(count_raw))
            count = parsed if parsed > 0 else None
        except (TypeError, ValueError):
            count = None
    if rating is None:
        return None, None
    return rating, count


def _recipe_card(recipe: dict[str, Any], *, folder_id: str | None = None) -> dict[str, Any]:
    rid = str(recipe.get("id") or "")
    rating, rating_count = _rating_fields(recipe)
    card: dict[str, Any] = {
        "recipe_id": rid,
        "title": recipe.get("title") or rid,
        "preparation_time": _prep_minutes(recipe),
        "image_url": _image_url(recipe.get("previewImageUrlTemplate")),
        "app_url": recipe.get("siteUrl")
        or (f"https://www.chefkoch.de/rezepte/{rid}.html" if rid else None),
        "viewer_url": None,
        "source": SOURCE_CHEFKOCH,
        "rating": rating,
        "rating_count": rating_count,
    }
    if folder_id:
        card["folder_id"] = folder_id
    return card


class ChefkochCollectionsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll Chefkoch cookbook collections into FWL-shaped data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.entry = entry
        self._session = async_create_clientsession(
            hass, cookie_jar=aiohttp.CookieJar(unsafe=True)
        )
        self._api_token: str | None = None
        self._user_id: str | None = None
        self._username: str | None = None
        self._has_meal_planner = False

    @property
    def user_id(self) -> str | None:
        return self._user_id

    @property
    def has_meal_planner(self) -> bool:
        return self._has_meal_planner

    def _api_headers(self) -> dict[str, str]:
        if not self._api_token:
            raise UpdateFailed("Not authenticated")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Chefkoch-Api-Token": self._api_token,
        }

    def _cookbook_base(self) -> str:
        if not self._user_id:
            raise UpdateFailed("Missing user id")
        return f"{API_BASE}/cookbooks/user-{self._user_id}"

    def validate_collection_id(self, folder_id: str) -> str:
        """Ensure folder id is a safe full collection id for this user."""
        fid = str(folder_id or "").strip()
        if not fid or "/" in fid or "\\" in fid or ".." in fid or "?" in fid:
            raise ValueError("Invalid Chefkoch folder id")
        if not self._user_id:
            raise UpdateFailed("Missing user id")
        prefix = f"user-{self._user_id}-"
        if not fid.startswith(prefix) or not _COLLECTION_ID_RE.match(fid):
            raise ValueError(
                f"Chefkoch folder id must look like {prefix}N (full collection id)"
            )
        return fid

    async def async_login(self) -> None:
        """Authenticate and cache api token + user id."""
        email = self.entry.data[CONF_EMAIL]
        password = self.entry.data[CONF_PASSWORD]
        async with self._session.post(
            AUTH_URL,
            json={
                "identifier": email,
                "password": password,
                "context": "login/init",
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise ConfigEntryAuthFailed(
                    f"Chefkoch login failed ({resp.status}): {text[:200]}"
                )
            _ = await resp.json(content_type=None)

        async with self._session.get(
            ME_URL, headers={"Accept": "application/json"}
        ) as resp:
            if resp.status >= 400:
                raise ConfigEntryAuthFailed(f"Chefkoch /me failed ({resp.status})")
            me = await resp.json(content_type=None)

        token = me.get("api_token")
        uid = me.get("id")
        if not token or not uid:
            raise ConfigEntryAuthFailed("Chefkoch login did not return api_token/id")
        self._api_token = str(token)
        self._user_id = str(uid)
        self._username = me.get("username")
        roles = me.get("roles") or []
        entitlements = me.get("entitlements") or []
        self._has_meal_planner = (
            "ROLE_ENTITLEMENT_MEAL_PLANNER" in roles
            or "ROLE_ENTITLEMENT_MEAL_PLANNER" in entitlements
            or any("MEAL_PLANNER" in str(x) for x in list(roles) + list(entitlements))
        )

    async def _async_ensure_login(self) -> None:
        if self._api_token and self._user_id:
            return
        await self.async_login()

    async def _async_get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict | None = None,
    ) -> Any:
        async with self._session.get(url, headers=headers, params=params) as resp:
            if resp.status in (401, 403) and headers and "X-Chefkoch-Api-Token" in headers:
                await self.async_login()
                headers = self._api_headers()
                async with self._session.get(
                    url, headers=headers, params=params
                ) as resp2:
                    if resp2.status >= 400:
                        text = await resp2.text()
                        raise UpdateFailed(f"GET {url} -> {resp2.status}: {text[:200]}")
                    return await resp2.json(content_type=None)
            if resp.status >= 400:
                text = await resp.text()
                raise UpdateFailed(f"GET {url} -> {resp.status}: {text[:200]}")
            return await resp.json(content_type=None)

    def _parse_response_body(self, text: str) -> Any:
        if not text:
            return {}
        try:
            return _json.loads(text)
        except Exception:  # noqa: BLE001
            return {"raw": text}

    async def _async_request_json(
        self, method: str, url: str, *, json_body: dict | None = None
    ) -> Any:
        await self._async_ensure_login()
        headers = self._api_headers()
        async with self._session.request(
            method, url, headers=headers, json=json_body
        ) as resp:
            text = await resp.text()
            if resp.status in (401, 403):
                await self.async_login()
                headers = self._api_headers()
                async with self._session.request(
                    method, url, headers=headers, json=json_body
                ) as resp2:
                    text2 = await resp2.text()
                    if resp2.status >= 400:
                        raise HomeAssistantError(
                            f"{method} {url} -> {resp2.status}: {text2[:300]}"
                        )
                    return self._parse_response_body(text2)
            if resp.status >= 400:
                raise HomeAssistantError(f"{method} {url} -> {resp.status}: {text[:300]}")
            return self._parse_response_body(text)

    async def _async_paginate(
        self, url: str, *, headers: dict[str, str], extra_params: dict[str, Any]
    ) -> list[Any]:
        """Fetch all pages of a Chefkoch list endpoint."""
        results: list[Any] = []
        offset = 0
        for _ in range(_MAX_PAGES):
            params = {
                **extra_params,
                "offset": offset,
                "limit": _PAGE_SIZE,
            }
            data = await self._async_get_json(url, headers=headers, params=params)
            batch = data.get("results") if isinstance(data, dict) else None
            if not isinstance(batch, list):
                batch = []
            results.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break
            total = None
            for key in ("count", "total", "numResults", "resultCount"):
                if isinstance(data, dict) and data.get(key) is not None:
                    try:
                        total = int(data[key])
                    except (TypeError, ValueError):
                        total = None
                    break
            if total is not None and len(results) >= total:
                break
            offset += _PAGE_SIZE
        return results

    async def async_create_folder(self, name: str) -> str:
        """Create a cookbook collection; return its id."""
        data = await self._async_request_json(
            "POST", f"{self._cookbook_base()}/collections", json_body={"name": name}
        )
        for msg in (data.get("notification") or {}).get("messages") or []:
            coll = msg.get("collection") or {}
            if coll.get("id"):
                return str(coll["id"])
        raise UpdateFailed("Could not create Chefkoch collection")

    def _default_collection_id(self) -> str:
        if not self._user_id:
            raise UpdateFailed("Missing user id")
        return f"user-{self._user_id}-0"

    def _is_default_collection(self, folder_id: str) -> bool:
        return folder_id == self._default_collection_id()

    async def async_delete_folder(self, folder_id: str) -> None:
        """Delete an empty collection (never Hauptsammlung)."""
        await self._async_ensure_login()
        folder_id = self.validate_collection_id(folder_id)
        if self._is_default_collection(folder_id):
            raise ValueError("Hauptsammlung cannot be deleted")
        for folder in (self.data or {}).get("favorite_folders") or []:
            if folder.get("id") == folder_id and int(folder.get("count") or 0) > 0:
                raise ValueError("Folder is not empty")
        url = f"{self._cookbook_base()}/collections/{folder_id}?withRecipes=0"
        await self._async_request_json("DELETE", url)

    async def async_move_favorite(
        self, recipe_id: str, *, to_folder_id: str | None
    ) -> None:
        """Move recipe into a collection (or Hauptsammlung / uncategorized when None)."""
        await self._async_ensure_login()
        if to_folder_id in (None, "", "__uncategorized__"):
            target = self._default_collection_id()
        else:
            target = self.validate_collection_id(str(to_folder_id))
        await self._async_request_json(
            "PATCH",
            f"{self._cookbook_base()}/saved-recipes",
            json_body={"recipeIds": [recipe_id], "collectionIds": [target]},
        )

    async def async_add_weekplan_meal(self, day: date, recipe_id: str) -> None:
        """Add recipe to Chefkoch week plan (requires Plus meal planner)."""
        await self._async_ensure_login()
        if not self._has_meal_planner:
            raise PermissionError(
                "Chefkoch meal planner requires a Plus entitlement "
                "(ROLE_ENTITLEMENT_MEAL_PLANNER)"
            )
        body = {
            "date": day.isoformat(),
            "recipe": f"/wochenplaner/api/recipes/{recipe_id}",
        }
        await self._async_request_json("POST", WEEKPLAN_ENTRIES_URL, json_body=body)

    async def async_remove_weekplan_meal(self, day: date, recipe_id: str) -> None:
        """Remove a recipe from the Chefkoch week plan day."""
        await self._async_ensure_login()
        if not self._has_meal_planner:
            raise PermissionError(
                "Chefkoch meal planner requires a Plus entitlement "
                "(ROLE_ENTITLEMENT_MEAL_PLANNER)"
            )
        meals = await self._async_fetch_week_meals()
        entry_id = None
        for meal in meals:
            if meal.get("date") == day.isoformat() and meal.get("recipe_id") == recipe_id:
                entry_id = meal.get("entry_id")
                break
        if not entry_id:
            raise UpdateFailed("Weekplan entry not found")
        entry_ref = str(entry_id)
        if entry_ref.startswith("/"):
            url = f"https://www.chefkoch.de{entry_ref}"
        elif entry_ref.startswith("http"):
            url = entry_ref
        else:
            url = f"{WEEKPLAN_ENTRIES_URL}/{quote(entry_ref, safe='')}"
        await self._async_request_json("DELETE", url)

    async def _async_fetch_favorites(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return (favorite_folders, uncategorized).

        Chefkoch Hauptsammlung (``user-{uid}-0``) is mapped to FWL-shaped
        ``uncategorized`` so joined Lovelace cards share one “Ohne Ordner”
        section. Other collections stay in ``favorite_folders``.
        """
        await self._async_ensure_login()
        headers = self._api_headers()
        default_id = self._default_collection_id()
        collections = await self._async_paginate(
            f"{self._cookbook_base()}/collections",
            headers=headers,
            extra_params={"order": 0, "orderBy": 2},
        )
        folders: list[dict[str, Any]] = []
        uncategorized: list[dict[str, Any]] = []
        for raw in collections:
            folder_id = str(raw.get("id") or "")
            if not folder_id:
                continue
            recipe_rows = await self._async_paginate(
                f"{self._cookbook_base()}/collections/{folder_id}/recipes",
                headers=headers,
                extra_params={"order": 0, "orderBy": 2},
            )
            is_default = folder_id == default_id
            recipes: list[dict[str, Any]] = []
            for row in recipe_rows:
                recipe = row.get("recipe") or {}
                if not recipe.get("id"):
                    continue
                # Uncategorized cards omit folder_id (FWL / Cookidoo parity).
                recipes.append(
                    _recipe_card(
                        recipe, folder_id=None if is_default else folder_id
                    )
                )
            recipes.sort(key=lambda r: (r.get("title") or "").lower())
            if is_default:
                uncategorized = recipes
                continue
            folders.append(
                {
                    "id": folder_id,
                    "name": raw.get("name") or "Sammlung",
                    "count": len(recipes),
                    "recipes": recipes,
                    "source": SOURCE_CHEFKOCH,
                }
            )
        folders.sort(key=lambda f: (f.get("name") or "").lower())
        return folders, uncategorized

    async def _async_fetch_week_meals(self) -> list[dict[str, Any]]:
        await self._async_ensure_login()
        if not self._has_meal_planner:
            return []
        today = date.today()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=13)
        try:
            data = await self._async_get_json(
                WEEKPLAN_ENTRIES_URL,
                headers={"Accept": "application/json"},
                params={
                    "date[after]": start.isoformat(),
                    "date[before]": end.isoformat(),
                },
            )
        except UpdateFailed as err:
            _LOGGER.debug("Chefkoch weekplan unavailable: %s", err)
            return []

        members: list[Any]
        if isinstance(data, list):
            members = data
        elif isinstance(data, dict):
            members = (
                data.get("hydra:member")
                or data.get("member")
                or data.get("results")
                or data.get("data")
                or []
            )
        else:
            members = []

        meals: list[dict[str, Any]] = []
        for entry in members:
            if not isinstance(entry, dict):
                continue
            recipe = entry.get("recipe") or {}
            if isinstance(recipe, str):
                # IRI-only — no enrichment without Plus fixtures to verify.
                continue
            rid = str(recipe.get("id") or entry.get("recipeId") or "")
            day = entry.get("date") or entry.get("day")
            if isinstance(day, str) and "T" in day:
                day = day[:10]
            if not rid or not day:
                continue
            card = _recipe_card(recipe)
            card["date"] = day
            card["entry_id"] = entry.get("id") or entry.get("@id")
            meals.append(card)
        return meals

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            await self._async_ensure_login()
            folders, uncategorized = await self._async_fetch_favorites()
            week_meals = await self._async_fetch_week_meals()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err

        total = sum(int(f.get("count") or 0) for f in folders) + len(uncategorized)
        return {
            "favorite_count": total,
            "favorite_folders": folders,
            "uncategorized": uncategorized,
            "week_meals": week_meals,
            ATTR_HAS_MEAL_PLANNER: self._has_meal_planner,
            "username": self._username,
            "source": SOURCE_CHEFKOCH,
        }

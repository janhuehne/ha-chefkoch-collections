"""Fetch Chefkoch cookbook collections + optional week plan."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

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


def _image_url(template: str | None) -> str | None:
    if not template:
        return None
    return template.replace("<format>", IMAGE_FORMAT).replace(
        "\u003cformat\u003e", IMAGE_FORMAT
    )


def _recipe_card(recipe: dict[str, Any], *, folder_id: str | None = None) -> dict[str, Any]:
    rid = str(recipe.get("id") or "")
    card: dict[str, Any] = {
        "recipe_id": rid,
        "title": recipe.get("title") or rid,
        "preparation_time": recipe.get("preparationTime") or recipe.get("totalTime"),
        "image_url": _image_url(recipe.get("previewImageUrlTemplate")),
        "app_url": recipe.get("siteUrl")
        or (f"https://www.chefkoch.de/rezepte/{rid}.html" if rid else None),
        "viewer_url": None,
        "source": SOURCE_CHEFKOCH,
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
                raise ConfigEntryAuthFailed(f"Chefkoch login failed ({resp.status}): {text[:200]}")
            # body mainly has redirectUrl; session cookies matter
            _ = await resp.json(content_type=None)

        async with self._session.get(ME_URL, headers={"Accept": "application/json"}) as resp:
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
        self, url: str, *, headers: dict[str, str] | None = None, params: dict | None = None
    ) -> Any:
        async with self._session.get(url, headers=headers, params=params) as resp:
            if resp.status in (401, 403) and headers and "X-Chefkoch-Api-Token" in headers:
                # retry once after re-login
                await self.async_login()
                headers = self._api_headers()
                async with self._session.get(url, headers=headers, params=params) as resp2:
                    if resp2.status >= 400:
                        text = await resp2.text()
                        raise UpdateFailed(f"GET {url} -> {resp2.status}: {text[:200]}")
                    return await resp2.json(content_type=None)
            if resp.status >= 400:
                text = await resp.text()
                raise UpdateFailed(f"GET {url} -> {resp.status}: {text[:200]}")
            return await resp.json(content_type=None)

    async def _async_request_json(
        self, method: str, url: str, *, json_body: dict | None = None
    ) -> Any:
        await self._async_ensure_login()
        headers = self._api_headers()
        async with self._session.request(
            method, url, headers=headers, json=json_body
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise HomeAssistantError(f"{method} {url} -> {resp.status}: {text[:300]}")
            if not text:
                return {}
            try:
                import json as _json

                return _json.loads(text)
            except Exception:  # noqa: BLE001
                return {"raw": text}

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

    async def async_delete_folder(self, folder_id: str) -> None:
        """Delete an empty collection."""
        await self._async_ensure_login()
        for folder in (self.data or {}).get("favorite_folders") or []:
            if folder.get("id") == folder_id and int(folder.get("count") or 0) > 0:
                raise ValueError("Folder is not empty")
        url = f"{self._cookbook_base()}/collections/{folder_id}?withRecipes=0"
        await self._async_request_json("DELETE", url)

    async def async_move_favorite(
        self, recipe_id: str, *, to_folder_id: str | None
    ) -> None:
        """Move recipe into a collection (or default when None)."""
        await self._async_ensure_login()
        target = to_folder_id or f"user-{self._user_id}-0"
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
        # API Platform-style create; verified shape may vary with Plus accounts.
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
        await self._async_request_json("DELETE", f"{WEEKPLAN_ENTRIES_URL}/{entry_id}")

    async def _async_fetch_folders(self) -> list[dict[str, Any]]:
        await self._async_ensure_login()
        headers = self._api_headers()
        data = await self._async_get_json(
            f"{self._cookbook_base()}/collections",
            headers=headers,
            params={"offset": 0, "limit": 100, "order": 0, "orderBy": 2},
        )
        folders: list[dict[str, Any]] = []
        for raw in data.get("results") or []:
            folder_id = str(raw.get("id") or "")
            if not folder_id:
                continue
            recipes_data = await self._async_get_json(
                f"{self._cookbook_base()}/collections/{folder_id}/recipes",
                headers=headers,
                params={"offset": 0, "limit": 100, "order": 0, "orderBy": 2},
            )
            recipes: list[dict[str, Any]] = []
            for row in recipes_data.get("results") or []:
                recipe = row.get("recipe") or {}
                if not recipe.get("id"):
                    continue
                recipes.append(_recipe_card(recipe, folder_id=folder_id))
            recipes.sort(key=lambda r: (r.get("title") or "").lower())
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
        return folders

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
                # IRI only — skip enrichment for now
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
            folders = await self._async_fetch_folders()
            week_meals = await self._async_fetch_week_meals()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err

        total = sum(int(f.get("count") or 0) for f in folders)
        return {
            "favorite_count": total,
            "favorite_folders": folders,
            "uncategorized": [],
            "week_meals": week_meals,
            ATTR_HAS_MEAL_PLANNER: self._has_meal_planner,
            "username": self._username,
            "source": SOURCE_CHEFKOCH,
        }

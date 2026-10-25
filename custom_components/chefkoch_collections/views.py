"""HTTP API for Chefkoch Collections favorites (full nested payload)."""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import ATTR_HAS_MEAL_PLANNER, DOMAIN, SOURCE_CHEFKOCH
from .coordinator import ChefkochCollectionsCoordinator

_VIEW_KEY = f"{DOMAIN}_favorites_view_registered"


def async_setup_views(hass: HomeAssistant) -> None:
    """Register favorites API once."""
    if hass.data.get(_VIEW_KEY):
        return
    hass.http.register_view(ChefkochFavoritesView())
    hass.data[_VIEW_KEY] = True


def _primary_entry(hass: HomeAssistant) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


class ChefkochFavoritesView(HomeAssistantView):
    """Return full favorites payload for Lovelace join cards."""

    url = "/api/chefkoch_collections/favorites"
    name = "api:chefkoch_collections:favorites"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry = _primary_entry(hass)
        if entry is None:
            return web.json_response({"error": "not_configured"}, status=404)

        coordinator: ChefkochCollectionsCoordinator | None = getattr(
            entry, "runtime_data", None
        )
        if coordinator is None:
            return web.json_response({"error": "not_ready"}, status=503)

        data = coordinator.data or {}
        return web.json_response(
            {
                "favorite_count": data.get("favorite_count", 0),
                "favorite_folders": data.get("favorite_folders") or [],
                "uncategorized": data.get("uncategorized") or [],
                "week_meals": data.get("week_meals") or [],
                ATTR_HAS_MEAL_PLANNER: data.get(ATTR_HAS_MEAL_PLANNER, False),
                "source": SOURCE_CHEFKOCH,
                "username": data.get("username"),
            }
        )

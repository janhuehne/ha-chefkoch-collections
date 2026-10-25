"""Constants for Chefkoch Collections."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "chefkoch_collections"

CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"

DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=30)

ATTR_FAVORITE_COUNT: Final = "favorite_count"
ATTR_FAVORITE_FOLDERS: Final = "favorite_folders"
ATTR_SOURCE: Final = "source"
ATTR_WEEK_MEALS: Final = "week_meals"
ATTR_HAS_MEAL_PLANNER: Final = "has_meal_planner"

SOURCE_CHEFKOCH: Final = "chefkoch"

API_BASE: Final = "https://api.chefkoch.de/v2"
WEB_BASE: Final = "https://www.chefkoch.de"
AUTH_URL: Final = f"{WEB_BASE}/benutzer/api/authenticate"
ME_URL: Final = f"{WEB_BASE}/benutzer/me"
WEEKPLAN_ENTRIES_URL: Final = f"{WEB_BASE}/wochenplaner/api/recipe_entries"

IMAGE_FORMAT: Final = "crop-360x240"

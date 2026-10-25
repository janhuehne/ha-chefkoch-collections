"""Sensors for Chefkoch Collections."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ChefkochCollectionsConfigEntry
from .const import (
    ATTR_FAVORITE_COUNT,
    ATTR_FAVORITE_FOLDERS,
    ATTR_HAS_MEAL_PLANNER,
    ATTR_SOURCE,
    ATTR_UNCATEGORIZED,
    ATTR_WEEK_MEALS,
    DOMAIN,
    SOURCE_CHEFKOCH,
)
from .coordinator import ChefkochCollectionsCoordinator

SENSOR_FAVORITES = SensorEntityDescription(
    key="favorites",
    name="Favoriten",
    icon="mdi:heart-multiple",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChefkochCollectionsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    _ = hass
    coordinator = entry.runtime_data
    async_add_entities(
        [ChefkochCollectionsFavoritesSensor(coordinator, entry.entry_id)]
    )


class ChefkochCollectionsFavoritesSensor(
    CoordinatorEntity[ChefkochCollectionsCoordinator], SensorEntity
):
    """Favorites-shaped sensor for Chefkoch cookbook collections."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ChefkochCollectionsCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = SENSOR_FAVORITES
        self._attr_unique_id = f"{entry_id}_favorites"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Chefkoch Collections",
            "manufacturer": "Chefkoch (unofficial bridge)",
            "model": "Cookbook collections",
        }
        self._update_from_coordinator()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_from_coordinator()
        self.async_write_ha_state()

    def _update_from_coordinator(self) -> None:
        data = self.coordinator.data or {}
        self._attr_native_value = data.get("favorite_count", 0)
        self._attr_extra_state_attributes = {
            ATTR_FAVORITE_COUNT: data.get("favorite_count", 0),
            ATTR_FAVORITE_FOLDERS: data.get("favorite_folders") or [],
            ATTR_UNCATEGORIZED: data.get("uncategorized") or [],
            ATTR_WEEK_MEALS: data.get("week_meals") or [],
            ATTR_HAS_MEAL_PLANNER: data.get(ATTR_HAS_MEAL_PLANNER, False),
            ATTR_SOURCE: SOURCE_CHEFKOCH,
        }

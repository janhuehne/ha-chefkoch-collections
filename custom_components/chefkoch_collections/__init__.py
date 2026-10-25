"""Chefkoch Collections — favorites + weekplan bridge with write services."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ChefkochCollectionsCoordinator
from .services import async_setup_services, async_unload_services
from .views import async_setup_views

PLATFORMS: list[Platform] = [Platform.SENSOR]

type ChefkochCollectionsConfigEntry = ConfigEntry[ChefkochCollectionsCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: ChefkochCollectionsConfigEntry
) -> bool:
    """Set up Chefkoch Collections from a config entry."""
    coordinator = ChefkochCollectionsCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    async_setup_views(hass)
    await async_setup_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ChefkochCollectionsConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and not hass.config_entries.async_entries(DOMAIN):
        async_unload_services(hass)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry versions (none yet)."""
    _ = hass
    return True

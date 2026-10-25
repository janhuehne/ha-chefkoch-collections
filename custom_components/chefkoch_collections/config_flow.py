"""Config flow for Chefkoch Collections."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import AUTH_URL, CONF_EMAIL, CONF_PASSWORD, DOMAIN, ME_URL

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)


async def _async_validate_login(
    session: aiohttp.ClientSession, email: str, password: str
) -> dict[str, str]:
    async with session.post(
        AUTH_URL,
        json={
            "identifier": email,
            "password": password,
            "context": "login/init",
        },
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    ) as resp:
        if resp.status >= 400:
            raise ValueError("invalid_auth")
    async with session.get(ME_URL, headers={"Accept": "application/json"}) as resp:
        if resp.status >= 400:
            raise ValueError("invalid_auth")
        me = await resp.json(content_type=None)
    if not me.get("api_token") or not me.get("id"):
        raise ValueError("invalid_auth")
    return {
        "username": str(me.get("username") or email),
        "user_id": str(me["id"]),
    }


class ChefkochCollectionsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chefkoch Collections."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_create_clientsession(
                self.hass, cookie_jar=aiohttp.CookieJar(unsafe=True)
            )
            try:
                info = await _async_validate_login(
                    session,
                    str(user_input[CONF_EMAIL]).strip(),
                    str(user_input[CONF_PASSWORD]),
                )
            except ValueError:
                errors["base"] = "invalid_auth"
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected Chefkoch login error")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["user_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Chefkoch Collections ({info['username']})",
                    data={
                        CONF_EMAIL: str(user_input[CONF_EMAIL]).strip(),
                        CONF_PASSWORD: str(user_input[CONF_PASSWORD]),
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

"""Config flow for Chefkoch Collections."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
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


def _credentials_schema(
    *, email: str | None = None, require_email: bool = True
) -> vol.Schema:
    email_field: Any
    if require_email:
        email_field = vol.Required(CONF_EMAIL, default=email or "")
    else:
        email_field = vol.Optional(CONF_EMAIL, default=email or "")
    return vol.Schema(
        {
            email_field: TextSelector(
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

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None

    async def _async_try_login(
        self, email: str, password: str
    ) -> tuple[dict[str, str] | None, dict[str, str]]:
        session = async_create_clientsession(
            self.hass, cookie_jar=aiohttp.CookieJar(unsafe=True)
        )
        try:
            info = await _async_validate_login(session, email, password)
        except ValueError:
            return None, {"base": "invalid_auth"}
        except aiohttp.ClientError:
            return None, {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected Chefkoch login error")
            return None, {"base": "unknown"}
        return info, {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = str(user_input[CONF_EMAIL]).strip()
            password = str(user_input[CONF_PASSWORD])
            info, errors = await self._async_try_login(email, password)
            if info:
                await self.async_set_unique_id(info["user_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Chefkoch Collections ({info['username']})",
                    data={CONF_EMAIL: email, CONF_PASSWORD: password},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Re-authenticate when credentials are invalid."""
        _ = entry_data
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect updated credentials and reload the entry."""
        entry = self._reauth_entry or self._get_reauth_entry()
        errors: dict[str, str] = {}
        current_email = str(entry.data.get(CONF_EMAIL) or "")

        if user_input is not None:
            email = str(user_input.get(CONF_EMAIL) or current_email).strip()
            password = str(user_input[CONF_PASSWORD])
            info, errors = await self._async_try_login(email, password)
            if info:
                await self.async_set_unique_id(info["user_id"])
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_EMAIL: email, CONF_PASSWORD: password},
                    title=f"Chefkoch Collections ({info['username']})",
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_credentials_schema(email=current_email),
            errors=errors,
            description_placeholders={"email": current_email},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow updating stored credentials from the UI."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        current_email = str(entry.data.get(CONF_EMAIL) or "")

        if user_input is not None:
            email = str(user_input.get(CONF_EMAIL) or current_email).strip()
            password = str(user_input[CONF_PASSWORD])
            info, errors = await self._async_try_login(email, password)
            if info:
                await self.async_set_unique_id(info["user_id"])
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_EMAIL: email, CONF_PASSWORD: password},
                    title=f"Chefkoch Collections ({info['username']})",
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_credentials_schema(email=current_email),
            errors=errors,
        )

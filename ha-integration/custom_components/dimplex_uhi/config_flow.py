"""Config and options flow of the Dimplex System M (UHI) integration."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import UhiApiClient, UhiApiError, UhiAuthError
from .const import (
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LANGUAGE,
    CONF_NAME,
    CONF_PORT,
    CONF_STATE_INTERVAL,
    CONF_TOKEN,
    CONF_VERSION_INTERVAL,
    DEFAULT_DEVICE_NAME,
    DEFAULT_LANGUAGE,
    DEFAULT_STATE_INTERVAL,
    DEFAULT_VERSION_INTERVAL,
    DOMAIN,
    SUPPORTED_LANGUAGES,
)


def _build_base_url(host: str, port: int | None = None) -> str:
    host = host.strip()
    if "://" in host:
        parsed = urlparse(host)
        scheme = parsed.scheme or "http"
        netloc = parsed.netloc or parsed.path
        if port and ":" not in netloc:
            netloc = f"{netloc}:{port}"
        return f"{scheme}://{netloc}"
    if port:
        return f"http://{host}:{port}"
    return f"http://{host}"


async def _validate(hass, data: dict[str, Any]) -> dict[str, Any]:
    """Check the connection and determine device master data (MAC)."""
    session = async_get_clientsession(hass)
    base_url = _build_base_url(data[CONF_HOST], data.get(CONF_PORT))
    client = UhiApiClient(
        session,
        base_url,
        token=data.get(CONF_TOKEN) or None,
        device_id=data.get(CONF_DEVICE_ID) or None,
    )
    version = await client.get_version()
    uhi = version.get("uhi") or {}
    return {"mac": uhi.get("mac"), "base_url": base_url}


class DimplexUhiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Guided setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await _validate(self.hass, user_input)
            except UhiAuthError:
                errors["base"] = "invalid_auth"
            except UhiApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                if info.get("mac"):
                    await self.async_set_unique_id(info["mac"])
                    self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_DEVICE_NAME): str,
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT): cv.port,
                vol.Optional(CONF_TOKEN, default=""): str,
                vol.Optional(CONF_DEVICE_ID, default=""): str,
                vol.Required(
                    CONF_LANGUAGE, default=DEFAULT_LANGUAGE
                ): vol.In(list(SUPPORTED_LANGUAGES)),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DimplexUhiOptionsFlow(config_entry)


class DimplexUhiOptionsFlow(OptionsFlow):
    """Adjust language, display name and intervals."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        data = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LANGUAGE,
                    default=options.get(
                        CONF_LANGUAGE, data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
                    ),
                ): vol.In(list(SUPPORTED_LANGUAGES)),
                vol.Required(
                    CONF_STATE_INTERVAL,
                    default=options.get(
                        CONF_STATE_INTERVAL, DEFAULT_STATE_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                vol.Required(
                    CONF_VERSION_INTERVAL,
                    default=options.get(
                        CONF_VERSION_INTERVAL, DEFAULT_VERSION_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

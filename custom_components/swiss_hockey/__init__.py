"""Swiss Ice Hockey (National League) integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CARDS_FILENAME, DOMAIN, LOGO_DIR, URL_BASE, WS_TYPE_SUBSCRIBE
from .coordinator import SwissHockeyConfigEntry, SwissHockeyCoordinator
from .logos import logo_dir

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the cards and the websocket command once."""
    integration = await async_get_integration(hass, DOMAIN)
    folder = logo_dir(hass)
    await hass.async_add_executor_job(lambda: folder.mkdir(parents=True, exist_ok=True))
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(f"{URL_BASE}/{CARDS_FILENAME}", str(_FRONTEND_DIR / CARDS_FILENAME), True),
            StaticPathConfig(f"{URL_BASE}/{LOGO_DIR}", str(folder), True),
        ]
    )
    # Version in the URL so browsers load the new cards after an update.
    add_extra_js_url(hass, f"{URL_BASE}/{CARDS_FILENAME}?v={integration.version}")
    websocket_api.async_register_command(hass, ws_subscribe)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SwissHockeyConfigEntry) -> bool:
    coordinator = SwissHockeyCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: SwissHockeyConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SwissHockeyConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _coordinator(hass: HomeAssistant) -> SwissHockeyCoordinator | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    return None


@websocket_api.websocket_command({vol.Required("type"): WS_TYPE_SUBSCRIBE})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Send the league data to a card now and after every update."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Swiss Ice Hockey is not set up")
        return

    @callback
    def _push() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], coordinator.card_payload()))

    connection.subscriptions[msg["id"]] = coordinator.async_add_listener(_push)
    connection.send_result(msg["id"])
    _push()

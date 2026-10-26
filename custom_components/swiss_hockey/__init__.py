"""Swiss Ice Hockey (National League) integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CARDS_FILENAME, DATA_URL_BASE, DOMAIN, LOCAL_BASE, LOGO_DIR, URL_BASE, WS_TYPE_SUBSCRIBE
from .coordinator import SwissHockeyConfigEntry, SwissHockeyCoordinator
from .logos import logo_dir

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the cards and the websocket command once."""
    integration = await async_get_integration(hass, DOMAIN)
    www_ready = await hass.async_add_executor_job(_prepare_www, hass)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(f"{URL_BASE}/{CARDS_FILENAME}", str(_FRONTEND_DIR / CARDS_FILENAME), True),
            StaticPathConfig(f"{URL_BASE}/{LOGO_DIR}", str(logo_dir(hass)), True),
        ]
    )
    # /local (= /config/www) is served by Home Assistant from the very start, our own
    # route only once this integration is set up. Dashboards opened while Home
    # Assistant is still starting can therefore only load the cards from /local.
    # /local exists only if the www folder existed at start-up (else: next restart).
    base = LOCAL_BASE if www_ready else URL_BASE
    hass.data[DATA_URL_BASE] = base
    # Version in the URL so browsers load the new cards after an update.
    await _async_register_cards(hass, f"{base}/{CARDS_FILENAME}?v={integration.version}")
    websocket_api.async_register_command(hass, ws_subscribe)
    return True


def _prepare_www(hass: HomeAssistant) -> bool:
    """Copy the cards to /config/www/swiss_hockey. Returns True if /local is usable."""
    www = Path(hass.config.path("www"))
    existed = www.is_dir()
    target = www / DOMAIN
    target.mkdir(parents=True, exist_ok=True)
    logo_dir(hass).mkdir(parents=True, exist_ok=True)
    source = _FRONTEND_DIR / CARDS_FILENAME
    dest = target / CARDS_FILENAME
    data = source.read_bytes()
    if not dest.is_file() or dest.read_bytes() != data:
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
    return existed


def _is_ours(url: str) -> bool:
    path = str(url).split("?")[0]
    return path in (f"{URL_BASE}/{CARDS_FILENAME}", f"{LOCAL_BASE}/{CARDS_FILENAME}")


async def _async_register_cards(hass: HomeAssistant, url: str) -> None:
    """Make the cards known to the dashboards.

    Preferred: a Lovelace resource (storage mode). The dashboard loads it on every
    page load, also when the page was opened while Home Assistant was still starting.
    Fallback for YAML resource mode: extra module URL in the frontend.
    """
    lovelace = hass.data.get(LOVELACE_DATA)
    resources = getattr(lovelace, "resources", None)
    if lovelace is None or lovelace.resource_mode != MODE_STORAGE or resources is None:
        _LOGGER.debug("Lovelace resources not in storage mode, using extra module URL")
        add_extra_js_url(hass, url)
        return
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True
    for item in resources.async_items():
        if _is_ours(item.get("url", "")):
            if item.get("url") != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return
    await resources.async_create_item({"res_type": "module", "url": url})


async def _async_remove_cards(hass: HomeAssistant) -> None:
    """Remove the Lovelace resource again (integration deleted)."""
    lovelace = hass.data.get(LOVELACE_DATA)
    resources = getattr(lovelace, "resources", None)
    if lovelace is None or lovelace.resource_mode != MODE_STORAGE or resources is None:
        return
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True
    for item in list(resources.async_items()):
        if _is_ours(item.get("url", "")):
            await resources.async_delete_item(item["id"])


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


async def async_remove_entry(hass: HomeAssistant, entry: SwissHockeyConfigEntry) -> None:
    await _async_remove_cards(hass)


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

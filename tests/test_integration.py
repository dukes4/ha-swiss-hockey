"""Config flow, setup, sensors and websocket."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.swiss_hockey.const import (
    CONF_LOGOS,
    CONF_TEAM_ACRONYM,
    CONF_TEAM_ID,
    DOMAIN,
)

FIX = Path(__file__).parent / "fixtures"
STANDINGS = json.loads((FIX / "standings.json").read_text(encoding="utf-8"))
RESULTS = json.loads((FIX / "results.json").read_text(encoding="utf-8"))
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def sihf(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    aioclient_mock.get(re.compile(r"data\.sihf\.ch.*alias=standing"), json=STANDINGS)
    aioclient_mock.get(re.compile(r"data\.sihf\.ch.*alias=results"), json=RESULTS)
    aioclient_mock.get(re.compile(r"www\.sihf\.ch/Image/Club/\d+\.png"), content=PNG)
    return aioclient_mock


async def test_flow_creates_entry(hass: HomeAssistant, sihf: AiohttpClientMocker) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_LOGOS: True})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "team"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("custom_components.swiss_hockey.async_setup_entry", _ok)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TEAM_ID: "101151"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Swiss Ice Hockey – HC Davos"
    assert result["data"] == {CONF_LOGOS: True, CONF_TEAM_ID: 101151, CONF_TEAM_ACRONYM: "HCD"}


async def _ok(*_args) -> bool:
    return True


async def test_flow_cannot_connect(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(re.compile(r"data\.sihf\.ch"), status=500)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_LOGOS: False})
    assert result["step_id"] == "team"
    assert result["errors"] == {"base": "cannot_connect"}


async def _setup(hass: HomeAssistant, logos: bool) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Swiss Ice Hockey – HC Davos",
        data={CONF_LOGOS: logos, CONF_TEAM_ID: 101151, CONF_TEAM_ACRONYM: "HCD"},
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return entry


async def test_sensors(hass: HomeAssistant, sihf: AiohttpClientMocker, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-10-26T12:00:00+01:00")
    await _setup(hass, logos=False)

    rank = hass.states.get("sensor.hc_davos_rank")
    assert rank is not None and rank.state == "2"
    assert rank.attributes["points"] == 33
    assert hass.states.get("sensor.hc_davos_points").state == "33"
    assert hass.states.get("sensor.hc_davos_last_game").state == "SCB 4:1 HCD"
    assert hass.states.get("sensor.hc_davos_form").state == "WL"
    nxt = hass.states.get("sensor.hc_davos_next_game")
    assert nxt.state == "2026-10-27T18:45:00+00:00"
    assert nxt.attributes["opponent"] == "SCB"
    assert nxt.attributes["home_away"] == "home"
    assert nxt.attributes["home_logo"] is None  # no consent, no logo
    # no logo download without consent
    assert not any("Image/Club" in str(call[1]) for call in sihf.mock_calls)


async def test_logos_and_websocket(hass: HomeAssistant, sihf: AiohttpClientMocker, hass_ws_client) -> None:
    await _setup(hass, logos=True)
    assert any("Image/Club/101151.png" in str(call[1]) for call in sihf.mock_calls)
    assert hass.states.get("sensor.hc_davos_next_game").attributes["home_logo"] == (
        "/swiss_hockey_static/logos/101151.png"
    )

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "swiss_hockey/subscribe"})
    msg = await client.receive_json()
    assert msg["success"]
    event = (await client.receive_json())["event"]
    assert event["ready"] is True
    assert event["favourite"] == "HCD"
    assert event["season"] == "2026/27"
    assert [r["team"] for r in event["standings"]] == ["ZSC", "HCD", "SCB"]
    assert event["teams"]["HCD"]["logo"] == "/swiss_hockey_static/logos/101151.png"
    assert len(event["games"]) == 4  # canceled game left out
    assert event["lines"][0] == {"after": 6, "label": "Playoffs"}


async def test_options_change_team(hass: HomeAssistant, sihf: AiohttpClientMocker) -> None:
    entry = await _setup(hass, logos=False)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOGOS: False, CONF_TEAM_ID: "102126"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_TEAM_ACRONYM] == "SCB"


async def test_single_instance(hass: HomeAssistant, sihf: AiohttpClientMocker) -> None:
    await _setup(hass, logos=False)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_update_failed(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(re.compile(r"data\.sihf\.ch"), status=503)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_LOGOS: False, CONF_TEAM_ID: 101151, CONF_TEAM_ACRONYM: "HCD"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY


async def test_cards_registered_as_lovelace_resource(hass: HomeAssistant, sihf: AiohttpClientMocker) -> None:
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    from custom_components.swiss_hockey import _async_register_cards

    entry = await _setup(hass, logos=False)
    resources = hass.data[LOVELACE_DATA].resources
    urls = [r["url"] for r in resources.async_items()]
    assert len(urls) == 1 and urls[0].startswith("/swiss_hockey_static/swiss-hockey-cards.js?v=")

    # New version: same entry is updated, no duplicate
    await _async_register_cards(hass, "/swiss_hockey_static/swiss-hockey-cards.js?v=9.9.9")
    urls = [r["url"] for r in resources.async_items()]
    assert urls == ["/swiss_hockey_static/swiss-hockey-cards.js?v=9.9.9"]

    # Removing the integration removes the resource
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert list(resources.async_items()) == []

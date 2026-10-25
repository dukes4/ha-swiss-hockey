"""Config flow: logo consent first, then the favourite club."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import SihfClient, SihfError, Team, parse_standings
from .const import CONF_LOGOS, CONF_TEAM_ACRONYM, CONF_TEAM_ID, DOMAIN, NAME

_LOGGER = logging.getLogger(__name__)


async def _async_teams(hass: HomeAssistant) -> list[Team]:
    """Clubs of the current National League table, sorted by name."""
    client = SihfClient(async_get_clientsession(hass))
    rows = parse_standings(await client.standings())
    if not rows:
        # Playoffs: fall back to the complete league data.
        data = await client.fetch()
        rows = data.standings
    return sorted((r.team for r in rows), key=lambda t: t.name.lower())


def _team_selector(teams: list[Team]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=str(t.id), label=f"{t.name} ({t.acronym})") for t in teams],
            mode=SelectSelectorMode.DROPDOWN,
            sort=False,
        )
    )


class SwissHockeyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._logos = False
        self._teams: list[Team] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: consent to download the club logos."""
        if user_input is not None:
            self._logos = bool(user_input.get(CONF_LOGOS, False))
            return await self.async_step_team()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_LOGOS, default=False): BooleanSelector()}),
        )

    async def async_step_team(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 2: choose the favourite club."""
        errors: dict[str, str] = {}
        if not self._teams:
            try:
                self._teams = await _async_teams(self.hass)
            except SihfError as err:
                _LOGGER.warning("Could not load the clubs from data.sihf.ch: %s", err)
                errors["base"] = "cannot_connect"
        if user_input is not None and self._teams:
            team = next((t for t in self._teams if str(t.id) == user_input[CONF_TEAM_ID]), None)
            if team is not None:
                return self.async_create_entry(
                    title=f"{NAME.split(' (')[0]} – {team.name}",
                    data={CONF_LOGOS: self._logos, CONF_TEAM_ID: team.id, CONF_TEAM_ACRONYM: team.acronym},
                )
            errors["base"] = "unknown_team"
        if not self._teams:
            return self.async_show_form(step_id="team", data_schema=vol.Schema({}), errors=errors)
        return self.async_show_form(
            step_id="team",
            data_schema=vol.Schema({vol.Required(CONF_TEAM_ID): _team_selector(self._teams)}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SwissHockeyOptionsFlow:
        return SwissHockeyOptionsFlow()


class SwissHockeyOptionsFlow(OptionsFlow):
    """Change logo consent and favourite club later."""

    def __init__(self) -> None:
        self._teams: list[Team] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry
        current_logos = entry.options.get(CONF_LOGOS, entry.data.get(CONF_LOGOS, False))
        current_team = entry.options.get(CONF_TEAM_ID, entry.data.get(CONF_TEAM_ID))
        if not self._teams:
            try:
                self._teams = await _async_teams(self.hass)
            except SihfError as err:
                _LOGGER.warning("Could not load the clubs from data.sihf.ch: %s", err)
                errors["base"] = "cannot_connect"
        if user_input is not None and self._teams:
            team = next((t for t in self._teams if str(t.id) == user_input[CONF_TEAM_ID]), None)
            if team is not None:
                return self.async_create_entry(
                    data={
                        CONF_LOGOS: bool(user_input.get(CONF_LOGOS, False)),
                        CONF_TEAM_ID: team.id,
                        CONF_TEAM_ACRONYM: team.acronym,
                    }
                )
            errors["base"] = "unknown_team"
        schema: dict[Any, Any] = {vol.Required(CONF_LOGOS, default=bool(current_logos)): BooleanSelector()}
        if self._teams:
            schema[vol.Required(CONF_TEAM_ID, default=str(current_team))] = _team_selector(self._teams)
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema), errors=errors)

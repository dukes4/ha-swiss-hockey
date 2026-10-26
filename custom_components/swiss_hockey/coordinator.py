"""Data update coordinator for the Swiss Ice Hockey integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Game, LeagueData, SihfClient, SihfConnectionError, SihfError
from .const import (
    CONF_LOGOS,
    CONF_TEAM_ACRONYM,
    CONF_TEAM_ID,
    DATA_URL_BASE,
    DOMAIN,
    GAME_WINDOW_AFTER,
    GAME_WINDOW_BEFORE,
    LOGO_DIR,
    UPDATE_INTERVAL_GAME,
    UPDATE_INTERVAL_IDLE,
    URL_BASE,
)
from .logos import async_available_logos, async_download_logos

_LOGGER = logging.getLogger(__name__)

type SwissHockeyConfigEntry = ConfigEntry[SwissHockeyCoordinator]


def _setting(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Options override the data from the initial setup."""
    return entry.options.get(key, entry.data.get(key, default))


class SwissHockeyCoordinator(DataUpdateCoordinator[LeagueData]):
    """Loads table and games, faster while a game is running."""

    config_entry: SwissHockeyConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SwissHockeyConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL_IDLE,
        )
        self._session = async_get_clientsession(hass)
        self.client = SihfClient(self._session)
        self.logo_ids: set[int] = set()

    @property
    def team_id(self) -> int:
        return int(_setting(self.config_entry, CONF_TEAM_ID))

    @property
    def team_acronym(self) -> str:
        return str(_setting(self.config_entry, CONF_TEAM_ACRONYM, ""))

    @property
    def logos_allowed(self) -> bool:
        return bool(_setting(self.config_entry, CONF_LOGOS, False))

    async def _async_update_data(self) -> LeagueData:
        try:
            data = await self.client.fetch()
        except SihfConnectionError as err:
            raise UpdateFailed(f"data.sihf.ch not reachable: {err}") from err
        except SihfError as err:
            raise UpdateFailed(f"data.sihf.ch returned unexpected data: {err}") from err

        if self.logos_allowed:
            ids = {row.team.id for row in data.standings}
            ids |= {t.id for g in data.games for t in (g.home, g.away)}
            self.logo_ids = await async_download_logos(self.hass, self._session, ids)
        else:
            self.logo_ids = set()

        self.update_interval = self._next_interval(data)
        return data

    def _next_interval(self, data: LeagueData) -> timedelta:
        """Poll often from shortly before face-off until the game is over."""
        now = dt_util.utcnow()
        for game in data.games:
            if game.canceled or game.finished:
                continue
            if game.live or game.start - GAME_WINDOW_BEFORE <= now <= game.start + GAME_WINDOW_AFTER:
                return UPDATE_INTERVAL_GAME
        return UPDATE_INTERVAL_IDLE

    async def async_refresh_logo_state(self) -> None:
        """Re-read which logos exist (after the consent changed)."""
        self.logo_ids = await async_available_logos(self.hass) if self.logos_allowed else set()

    # ---- payload for the Lovelace cards (sent over the websocket) ----

    def logo_url(self, team_id: int) -> str | None:
        if team_id in self.logo_ids:
            base = self.hass.data.get(DATA_URL_BASE, URL_BASE)
            return f"{base}/{LOGO_DIR}/{team_id}.png"
        return None

    def _game(self, game: Game) -> dict[str, Any]:
        return {
            "id": game.game_id,
            "start": game.start.isoformat(),
            "home": game.home.acronym,
            "away": game.away.acronym,
            "hs": game.home_score,
            "as": game.away_score,
            "dec": game.decision,
            "status": game.status,
            "pct": game.percent,
            "tv": game.broadcasters,
        }

    def card_payload(self) -> dict[str, Any]:
        data = self.data
        if data is None:
            return {"ready": False}
        teams: dict[str, dict[str, Any]] = {}
        for row in data.standings:
            teams[row.team.acronym] = {"id": row.team.id, "name": row.team.name}
        for g in data.games:
            for t in (g.home, g.away):
                teams.setdefault(t.acronym, {"id": t.id, "name": t.name})
        for info in teams.values():
            info["logo"] = self.logo_url(info["id"])
        return {
            "ready": True,
            "season": data.season.name,
            "phase": data.season.phase_name,
            "favourite": self.team_acronym,
            "teams": teams,
            "standings": [
                {
                    "rank": r.rank,
                    "team": r.team.acronym,
                    "gp": r.games_played,
                    "pts": r.points,
                    "w": r.wins,
                    "otw": r.ot_wins + r.so_wins,
                    "otl": r.ot_losses + r.so_losses,
                    "l": r.losses,
                    "gf": r.goals_for,
                    "ga": r.goals_against,
                    "streak": r.streak,
                }
                for r in data.standings
            ],
            "lines": [{"after": ln.after_rank, "label": ln.label} for ln in data.lines],
            "games": [self._game(g) for g in data.games if not g.canceled],
            "updated": data.updated.isoformat() if data.updated else None,
        }

"""Sensors for the favourite club."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Game
from .const import DOMAIN, NAME
from .coordinator import SwissHockeyConfigEntry, SwissHockeyCoordinator

PARALLEL_UPDATES = 0


def _result(game: Game, team_id: int) -> str:
    """'W' or 'L' from the point of view of the team."""
    if game.home_score is None or game.away_score is None:
        return ""
    mine, other = (game.home_score, game.away_score) if game.home.id == team_id else (game.away_score, game.home_score)
    return "W" if mine > other else "L"


def _score_text(game: Game) -> str:
    if game.home_score is None or game.away_score is None:
        return ""
    text = f"{game.home.acronym} {game.home_score}:{game.away_score} {game.away.acronym}"
    return f"{text} ({game.decision})" if game.decision else text


def _game_attrs(coord: SwissHockeyCoordinator, game: Game) -> dict[str, Any]:
    team_id = coord.team_id
    home = game.home.id == team_id
    opponent = game.away if home else game.home
    return {
        "home": game.home.acronym,
        "away": game.away.acronym,
        "home_name": game.home.name,
        "away_name": game.away.name,
        "home_logo": coord.logo_url(game.home.id),
        "away_logo": coord.logo_url(game.away.id),
        "opponent": opponent.acronym,
        "opponent_name": opponent.name,
        "home_away": "home" if home else "away",
        "home_score": game.home_score,
        "away_score": game.away_score,
        "decision": game.decision,
        "status": game.status,
        "progress": game.percent,
        "live": game.live,
        "tv": ", ".join(game.broadcasters),
    }


@dataclass(frozen=True, kw_only=True)
class SwissHockeySensorDescription(SensorEntityDescription):
    """Describes one sensor."""

    value_fn: Callable[[SwissHockeyCoordinator], Any]
    attrs_fn: Callable[[SwissHockeyCoordinator], dict[str, Any]] = lambda _c: {}


def _next_game(c: SwissHockeyCoordinator) -> datetime | None:
    game = c.data.next_game(c.team_id)
    return game.start if game else None


def _next_game_attrs(c: SwissHockeyCoordinator) -> dict[str, Any]:
    game = c.data.next_game(c.team_id)
    return _game_attrs(c, game) if game else {}


def _last_game(c: SwissHockeyCoordinator) -> str | None:
    games = c.data.last_games(c.team_id, 1)
    return _score_text(games[0]) if games else None


def _last_game_attrs(c: SwissHockeyCoordinator) -> dict[str, Any]:
    games = c.data.last_games(c.team_id, 1)
    if not games:
        return {}
    return {**_game_attrs(c, games[0]), "result": _result(games[0], c.team_id), "date": games[0].start.isoformat()}


def _form(c: SwissHockeyCoordinator) -> str | None:
    games = c.data.last_games(c.team_id, 5)
    return "".join(_result(g, c.team_id) for g in reversed(games)) or None


def _form_attrs(c: SwissHockeyCoordinator) -> dict[str, Any]:
    return {
        "games": [
            {
                "date": g.start.date().isoformat(),
                "score": _score_text(g),
                "result": _result(g, c.team_id),
                "home_away": "home" if g.home.id == c.team_id else "away",
            }
            for g in c.data.last_games(c.team_id, 5)
        ]
    }


def _rank(c: SwissHockeyCoordinator) -> int | None:
    row = c.data.standing(c.team_id)
    return row.rank if row else None


def _rank_attrs(c: SwissHockeyCoordinator) -> dict[str, Any]:
    row = c.data.standing(c.team_id)
    if not row:
        return {}
    return {
        "games_played": row.games_played,
        "points": row.points,
        "goals_for": row.goals_for,
        "goals_against": row.goals_against,
        "goal_difference": row.goal_difference,
        "season": c.data.season.name,
        "phase": c.data.season.phase_name,
    }


def _points(c: SwissHockeyCoordinator) -> int | None:
    row = c.data.standing(c.team_id)
    return row.points if row else None


SENSORS: tuple[SwissHockeySensorDescription, ...] = (
    SwissHockeySensorDescription(
        key="next_game",
        translation_key="next_game",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_next_game,
        attrs_fn=_next_game_attrs,
    ),
    SwissHockeySensorDescription(
        key="last_game",
        translation_key="last_game",
        value_fn=_last_game,
        attrs_fn=_last_game_attrs,
    ),
    SwissHockeySensorDescription(
        key="form",
        translation_key="form",
        value_fn=_form,
        attrs_fn=_form_attrs,
    ),
    SwissHockeySensorDescription(
        key="rank",
        translation_key="rank",
        value_fn=_rank,
        attrs_fn=_rank_attrs,
    ),
    SwissHockeySensorDescription(
        key="points",
        translation_key="points",
        state_class=SensorStateClass.TOTAL,
        value_fn=_points,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SwissHockeyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SwissHockeySensor(coordinator, desc) for desc in SENSORS)


class SwissHockeySensor(CoordinatorEntity[SwissHockeyCoordinator], SensorEntity):
    """A sensor about the favourite club."""

    _attr_has_entity_name = True
    _attr_attribution = "Data: data.sihf.ch (not affiliated with SIHF)"
    entity_description: SwissHockeySensorDescription
    _unrecorded_attributes = frozenset(
        {"games", "home_logo", "away_logo", "home_name", "away_name", "opponent_name", "tv"}
    )

    def __init__(self, coordinator: SwissHockeyCoordinator, description: SwissHockeySensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        team = coordinator.data.team(coordinator.team_id) if coordinator.data else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=team.name if team else coordinator.team_acronym,
            manufacturer=NAME,
            model="National League",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.sihf.ch",
        )

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        return self.entity_description.attrs_fn(self.coordinator)

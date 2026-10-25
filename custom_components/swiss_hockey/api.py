"""Client for the SIHF statistics interface (data.sihf.ch).

The interface is not officially documented. Everything that depends on its
layout is kept in this module, so a change on the SIHF side only needs a fix
here. Parsing is defensive: unknown or incomplete rows are skipped instead of
breaking the whole update.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp

from .const import API_BASE, LEAGUE_QUERY, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class SihfError(Exception):
    """Base error for the SIHF interface."""


class SihfConnectionError(SihfError):
    """The interface could not be reached."""


class SihfDataError(SihfError):
    """The interface answered with data we do not understand."""


@dataclass(slots=True)
class Team:
    """A club."""

    id: int
    acronym: str
    name: str


@dataclass(slots=True)
class StandingRow:
    """One line of the league table."""

    rank: int
    team: Team
    games_played: int
    points: int
    wins: int = 0
    ot_wins: int = 0
    so_wins: int = 0
    so_losses: int = 0
    ot_losses: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    streak: str = ""

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against


@dataclass(slots=True)
class TableLine:
    """A separator line in the table (e.g. after the last playoff place)."""

    after_rank: int
    label: str


@dataclass(slots=True)
class Game:
    """One game of the season."""

    game_id: str
    start: datetime
    home: Team
    away: Team
    home_score: int | None
    away_score: int | None
    decision: str  # "", "OT" or "SO"
    status: str
    percent: int  # 0 = not started, 100 = finished
    canceled: bool
    broadcasters: list[str] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.percent >= 100

    @property
    def live(self) -> bool:
        return 0 < self.percent < 100 and not self.canceled

    def involves(self, team_id: int) -> bool:
        return team_id in (self.home.id, self.away.id)


@dataclass(slots=True)
class Season:
    """Season and phase as currently selected by the interface."""

    alias: str  # e.g. "2027" for 2026/27
    name: str  # e.g. "2026/27"
    phase_id: str
    phase_name: str

    @property
    def date_from(self) -> str:
        return f"01.08.{int(self.alias) - 1}"

    @property
    def date_to(self) -> str:
        return f"31.05.{self.alias}"


@dataclass(slots=True)
class LeagueData:
    """Everything one update delivers."""

    season: Season
    standings: list[StandingRow]
    lines: list[TableLine]
    games: list[Game]
    updated: datetime | None

    def team(self, team_id: int) -> Team | None:
        for row in self.standings:
            if row.team.id == team_id:
                return row.team
        for game in self.games:
            for team in (game.home, game.away):
                if team.id == team_id:
                    return team
        return None

    def standing(self, team_id: int) -> StandingRow | None:
        return next((r for r in self.standings if r.team.id == team_id), None)

    def team_games(self, team_id: int) -> list[Game]:
        return [g for g in self.games if g.involves(team_id) and not g.canceled]

    def next_game(self, team_id: int) -> Game | None:
        """Live game, otherwise the next game that has not finished."""
        games = self.team_games(team_id)
        live = [g for g in games if g.live]
        if live:
            return live[0]
        upcoming = [g for g in games if not g.finished]
        return min(upcoming, key=lambda g: g.start) if upcoming else None

    def last_games(self, team_id: int, count: int = 5) -> list[Game]:
        """Finished games, newest first."""
        done = sorted(
            (g for g in self.team_games(team_id) if g.finished),
            key=lambda g: g.start,
            reverse=True,
        )
        return done[:count]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _score(value: Any) -> int | None:
    text = str(value).strip() if value is not None else ""
    return int(text) if text.isdigit() else None


def _team(obj: Any) -> Team | None:
    if not isinstance(obj, dict) or "acronym" not in obj:
        return None
    team_id = _int(obj.get("id") or obj.get("clubId"), -1)
    if team_id < 0:
        return None
    return Team(id=team_id, acronym=str(obj["acronym"]), name=str(obj.get("name") or obj["acronym"]))


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_season(payload: dict[str, Any]) -> Season:
    """Read the selected season and phase from the filter block."""
    filters = {f.get("alias", "").lower(): f for f in payload.get("filters") or [] if isinstance(f, dict)}
    season_f = filters.get("season")
    phase_f = filters.get("phase")
    if not season_f or not season_f.get("selected"):
        raise SihfDataError("No season in standings response")
    season_alias = str(season_f["selected"])
    season_name = next(
        (e.get("name") for e in season_f.get("entries", []) if str(e.get("alias")) == season_alias),
        season_alias,
    )
    phase_id = str(phase_f.get("selected", "")) if phase_f else ""
    phase_name = next(
        (e.get("name") for e in (phase_f or {}).get("entries", []) if str(e.get("alias")) == phase_id),
        phase_id,
    )
    return Season(alias=season_alias, name=str(season_name), phase_id=phase_id, phase_name=str(phase_name))


def regular_phase_id(payload: dict[str, Any]) -> str | None:
    """Phase id of the regular season, if the filter block lists one."""
    for f in payload.get("filters") or []:
        if isinstance(f, dict) and str(f.get("alias", "")).lower() == "phase":
            for entry in f.get("entries", []):
                if "regular" in str(entry.get("name", "")).lower():
                    return str(entry.get("alias"))
    return None


def parse_standings(payload: dict[str, Any]) -> list[StandingRow]:
    """Parse the league table. Rows we do not understand are skipped."""
    header = [h.get("alias") for h in payload.get("header") or [] if isinstance(h, dict)]
    idx = {name: i for i, name in enumerate(header)}
    needed = ("rank", "team", "gamesPlayed", "points")
    if not all(k in idx for k in needed):
        raise SihfDataError(f"Unexpected standings header: {header}")

    def col(row: list[Any], name: str, default: Any = 0) -> Any:
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else default

    rows: list[StandingRow] = []
    for row in payload.get("data") or []:
        if not isinstance(row, list):
            continue
        team = _team(col(row, "team", None))
        if team is None:
            continue
        rows.append(
            StandingRow(
                rank=_int(col(row, "rank")),
                team=team,
                games_played=_int(col(row, "gamesPlayed")),
                points=_int(col(row, "points")),
                wins=_int(col(row, "gamesWonInTime")),
                ot_wins=_int(col(row, "gamesWonExtraTime")),
                so_wins=_int(col(row, "gamesWonPenalty")),
                so_losses=_int(col(row, "gamesLostPenalty")),
                ot_losses=_int(col(row, "gamesLostExtraTime")),
                losses=_int(col(row, "gamesLostInTime")),
                goals_for=_int(col(row, "goalsFor")),
                goals_against=_int(col(row, "goalsAgainst")),
                streak=str(col(row, "streak", "") or ""),
            )
        )
    return sorted(rows, key=lambda r: r.rank)


def parse_lines(payload: dict[str, Any]) -> list[TableLine]:
    """Separator lines, e.g. name 'Playoffs,Play-In,,Playout' with rows [6, 10, 12]."""
    lines: list[TableLine] = []
    for item in payload.get("highlightedPositions") or []:
        if not isinstance(item, dict):
            continue
        labels = str(item.get("name", "")).split(",")
        for i, after in enumerate(item.get("rows") or []):
            label = labels[i].strip() if i < len(labels) else ""
            lines.append(TableLine(after_rank=_int(after), label=label))
    return lines


def parse_games(payload: dict[str, Any]) -> list[Game]:
    """Parse the results/schedule list."""
    header = [h.get("alias") for h in payload.get("header") or [] if isinstance(h, dict)]
    idx = {name: i for i, name in enumerate(header)}
    for key in ("homeTeam", "awayTeam", "score", "status"):
        if key not in idx:
            raise SihfDataError(f"Unexpected results header: {header}")

    def col(row: list[Any], name: str, default: Any = None) -> Any:
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else default

    games: list[Game] = []
    for row in payload.get("data") or []:
        if not isinstance(row, list):
            continue
        home = _team(col(row, "homeTeam"))
        away = _team(col(row, "awayTeam"))
        status = col(row, "status")
        if home is None or away is None or not isinstance(status, dict):
            continue
        start = _datetime(status.get("startDateTime"))
        if start is None:
            continue
        score = col(row, "score") or {}
        details = col(row, "details") or {}
        tv = col(row, "broadcasts") or next(
            (c for c in row if isinstance(c, dict) and c.get("type") == "broadcasts"), {}
        )
        decision = col(row, "decision", "")
        games.append(
            Game(
                game_id=str(details.get("gameId", "")) if isinstance(details, dict) else "",
                start=start,
                home=home,
                away=away,
                home_score=_score(score.get("homeTeam")) if isinstance(score, dict) else None,
                away_score=_score(score.get("awayTeam")) if isinstance(score, dict) else None,
                decision=decision if isinstance(decision, str) else "",
                status=str(status.get("name", "")),
                percent=_int(status.get("percent")),
                canceled=bool(status.get("canceled", False)),
                broadcasters=[str(x) for x in tv.get("entries", [])] if isinstance(tv, dict) else [],
            )
        )
    return sorted(games, key=lambda g: g.start)


class SihfClient:
    """Small async client for data.sihf.ch."""

    def __init__(self, session: aiohttp.ClientSession, language: str = "de") -> None:
        self._session = session
        self._language = language

    async def _get(self, params: dict[str, str]) -> dict[str, Any]:
        params = {**params, "language": self._language}
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await self._session.get(API_BASE, params=params)
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SihfConnectionError(f"data.sihf.ch not reachable: {err}") from err
        except ValueError as err:
            raise SihfDataError(f"data.sihf.ch returned no JSON: {err}") from err
        if not isinstance(payload, dict):
            raise SihfDataError("data.sihf.ch returned an unexpected structure")
        return payload

    async def standings(self, season: str | None = None, phase: str | None = None) -> dict[str, Any]:
        params = {"alias": "standing", "searchQuery": LEAGUE_QUERY}
        if season and phase:
            params |= {"filterQuery": f"{season}/{phase}", "filterBy": "Season,Phase"}
        return await self._get(params)

    async def games(self, season: Season) -> dict[str, Any]:
        return await self._get(
            {
                "alias": "results",
                "searchQuery": LEAGUE_QUERY,
                "filterQuery": f"{season.alias}/all/{season.date_from}-{season.date_to}/all/all/all",
                "filterBy": "season,phase,date,deferredState,team1,team2",
                "orderBy": "date",
                "orderByDescending": "false",
            }
        )

    async def fetch(self) -> LeagueData:
        """Detect the current season and load table and games."""
        payload = await self.standings()
        season = parse_season(payload)
        try:
            standings = parse_standings(payload)
        except SihfDataError:
            standings = []
        if not standings:
            # Playoffs/playouts: the default table may not be a league table.
            # Fall back to the regular season table of the same season.
            phase = regular_phase_id(payload)
            if phase and phase != season.phase_id:
                _LOGGER.debug("Standings phase %s not a table, using regular season", season.phase_name)
                payload = await self.standings(season.alias, phase)
                standings = parse_standings(payload)
        if not standings:
            raise SihfDataError("No standings rows found")
        games = parse_games(await self.games(season))
        return LeagueData(
            season=season,
            standings=standings,
            lines=parse_lines(payload),
            games=games,
            updated=_datetime(payload.get("updateDateTime")),
        )

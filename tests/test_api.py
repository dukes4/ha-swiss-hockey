"""Parsing of the data.sihf.ch responses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.swiss_hockey.api import (
    LeagueData,
    SihfDataError,
    parse_games,
    parse_lines,
    parse_season,
    parse_standings,
    regular_phase_id,
)

FIX = Path(__file__).parent / "fixtures"
HCD = 101151


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_season() -> None:
    season = parse_season(load("standings.json"))
    assert season.alias == "2027"
    assert season.name == "2026/27"
    assert season.phase_id == "657"
    assert season.phase_name == "Regular Season"
    assert season.date_from == "01.08.2026"
    assert season.date_to == "31.05.2027"


def test_season_missing() -> None:
    with pytest.raises(SihfDataError):
        parse_season({"filters": []})


def test_regular_phase() -> None:
    assert regular_phase_id(load("standings.json")) == "657"


def test_standings_skip_bad_rows() -> None:
    rows = parse_standings(load("standings.json"))
    assert [r.team.acronym for r in rows] == ["ZSC", "HCD", "SCB"]
    hcd = rows[1]
    assert (hcd.rank, hcd.games_played, hcd.points) == (2, 15, 33)
    assert hcd.goal_difference == 15
    assert hcd.ot_wins == 1 and hcd.so_losses == 1


def test_standings_unknown_header() -> None:
    with pytest.raises(SihfDataError):
        parse_standings({"header": [{"alias": "foo"}], "data": []})


def test_lines() -> None:
    lines = parse_lines(load("standings.json"))
    assert [(ln.after_rank, ln.label) for ln in lines] == [
        (6, "Playoffs"),
        (10, "Play-In"),
        (12, ""),
    ]


def test_games() -> None:
    games = parse_games(load("results.json"))
    assert len(games) == 5  # broken row skipped
    first = games[0]
    assert (first.home.acronym, first.home_score, first.away_score, first.decision) == ("HCD", 3, 2, "OT")
    assert first.finished and not first.live
    upcoming = games[2]
    assert upcoming.home_score is None and upcoming.percent == 0
    assert upcoming.broadcasters == ["MYSPORTS"]
    assert games[3].canceled


def _league() -> LeagueData:
    std = load("standings.json")
    return LeagueData(
        season=parse_season(std),
        standings=parse_standings(std),
        lines=parse_lines(std),
        games=parse_games(load("results.json")),
        updated=None,
    )


def test_team_views() -> None:
    data = _league()
    nxt = data.next_game(HCD)
    assert nxt is not None and nxt.game_id == "3"  # canceled game 4 ignored
    last = data.last_games(HCD)
    assert [g.game_id for g in last] == ["2", "1"]  # newest first
    assert data.standing(HCD).rank == 2
    assert data.team(HCD).name == "HC Davos"


def test_live_game_wins() -> None:
    data = _league()
    data.games[2].percent = 40
    data.games[2].home_score, data.games[2].away_score = 1, 0
    assert data.next_game(HCD).live

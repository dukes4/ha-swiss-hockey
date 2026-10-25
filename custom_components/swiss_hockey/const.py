"""Constants for the Swiss Ice Hockey (National League) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "swiss_hockey"
NAME: Final = "Swiss Ice Hockey (National League)"

# data.sihf.ch is the (undocumented) statistics interface behind sihf.ch.
API_BASE: Final = "https://data.sihf.ch/Statistic/api/cms/cache300"
# League filter used by sihf.ch for the National League pages.
LEAGUE_QUERY: Final = "1//1"
LOGO_URL: Final = "https://www.sihf.ch/Image/Club/{team_id}.png"

CONF_LOGOS: Final = "logos"
CONF_TEAM_ID: Final = "team_id"
CONF_TEAM_ACRONYM: Final = "team_acronym"

# Polling: quiet days vs. game windows (the interface itself caches for 5 minutes).
UPDATE_INTERVAL_IDLE: Final = timedelta(minutes=30)
UPDATE_INTERVAL_GAME: Final = timedelta(minutes=2)
GAME_WINDOW_BEFORE: Final = timedelta(minutes=10)
GAME_WINDOW_AFTER: Final = timedelta(hours=4)

REQUEST_TIMEOUT: Final = 30

# Frontend
URL_BASE: Final = "/swiss_hockey_static"
CARDS_FILENAME: Final = "swiss-hockey-cards.js"
LOGO_DIR: Final = "logos"  # below hass.config.path("www", DOMAIN)

WS_TYPE_SUBSCRIBE: Final = f"{DOMAIN}/subscribe"

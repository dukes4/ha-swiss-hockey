"""Club logos: only downloaded after the user's consent, stored locally."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiohttp
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGO_DIR, LOGO_URL, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def logo_dir(hass: HomeAssistant) -> Path:
    """Local folder for the logos (outside custom_components, survives updates)."""
    return Path(hass.config.path("www", DOMAIN, LOGO_DIR))


def _existing(folder: Path) -> set[int]:
    if not folder.is_dir():
        return set()
    return {int(p.stem) for p in folder.glob("*.png") if p.stem.isdigit()}


def _write(folder: Path, team_id: int, data: bytes) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{team_id}.png.tmp"
    tmp.write_bytes(data)
    tmp.replace(folder / f"{team_id}.png")


async def async_available_logos(hass: HomeAssistant) -> set[int]:
    """Team ids for which a logo is stored."""
    return await hass.async_add_executor_job(_existing, logo_dir(hass))


async def async_download_logos(hass: HomeAssistant, session: aiohttp.ClientSession, team_ids: set[int]) -> set[int]:
    """Download missing logos. Returns the ids that are available afterwards."""
    folder = logo_dir(hass)
    have = await hass.async_add_executor_job(_existing, folder)
    for team_id in sorted(team_ids - have):
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await session.get(LOGO_URL.format(team_id=team_id))
                resp.raise_for_status()
                data = await resp.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Logo %s not downloaded: %s", team_id, err)
            continue
        if not data.startswith(_PNG_MAGIC) or len(data) > 2_000_000:
            _LOGGER.debug("Logo %s is not a usable PNG, skipped", team_id)
            continue
        await hass.async_add_executor_job(_write, folder, team_id, data)
        have.add(team_id)
    return have

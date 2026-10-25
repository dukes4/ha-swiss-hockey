"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):  # noqa: ARG001
    """Load custom_components/ from this repository."""
    return


@pytest.fixture(autouse=True)
def isolated_logo_dir(tmp_path: Path):
    """Keep downloaded test logos out of the shared test config folder."""
    folder = tmp_path / "logos"
    with (
        patch("custom_components.swiss_hockey.logos.logo_dir", return_value=folder),
        patch("custom_components.swiss_hockey.logo_dir", return_value=folder),
    ):
        yield folder

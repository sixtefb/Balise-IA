from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from balise.config import SETTINGS


@pytest.fixture
def settings_with_tmp_cache(tmp_path: Path):
    return dataclasses.replace(SETTINGS, cache_db_path=tmp_path / "balise.duckdb")

from pathlib import Path

from retarank.config import CONTACT_CAPACITIES, LOOKBACK_DAYS, OUTCOME_DAYS, PROJECT_ROOT


def test_project_config_defaults() -> None:
    assert isinstance(PROJECT_ROOT, Path)
    assert LOOKBACK_DAYS == 180
    assert OUTCOME_DAYS == 90
    assert CONTACT_CAPACITIES == (0.10, 0.20, 0.30)

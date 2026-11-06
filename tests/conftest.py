import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings
from app.main import create_app


@pytest.fixture
def test_settings(tmp_path):
    return Settings(
        db_path=str(tmp_path / "cratewatch_test.db"),
        demo_mode=True,
        admin_token="test-token",
        background_rules=False,
        gap_threshold_seconds=1.0,
        sla_window_minutes=15,
        telemetry_interval_seconds=2.0,
    )


@pytest.fixture
def client(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as test_client:
        yield test_client

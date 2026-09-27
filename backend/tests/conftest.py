"""
Shared pytest fixtures (backend/tests/conftest.py).

Hermeticity against the developer's real repository-root `.env`: several test
modules assert the DEV-SPEC default unlock arithmetic (sketch +12h, report +24h),
so the settings that drive `timedelta(hours=settings.…)` are pinned to the spec
defaults for every test. Tests that exercise other values monkeypatch explicitly.
"""

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _pin_unlock_hour_defaults(monkeypatch):
    monkeypatch.setattr(settings, "soulmate_sketch_unlock_hours", 12)
    monkeypatch.setattr(settings, "soulmate_report_unlock_hours", 24)

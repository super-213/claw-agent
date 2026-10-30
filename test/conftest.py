"""Shared isolated family ledger fixtures."""
from family_task_helpers import family  # noqa: F401


# Application lifecycle tests must never start retention cleanup against a real
# family ledger. Individual board fixtures can replace this with their own clock.
import sys
import pytest
from services.board_store import BoardStore
from services.board_service import BoardPostService


@pytest.fixture(autouse=True)
def isolated_board_cleanup(tmp_path, monkeypatch):
    app = sys.modules.get('web_app')
    if app is not None:
        monkeypatch.setattr(app, 'family_board', BoardPostService(BoardStore(tmp_path / 'lifecycle-board.json'), app.family_members))


@pytest.fixture(autouse=True)
def isolated_activity_cleanup(tmp_path, monkeypatch):
    app = sys.modules.get('web_app')
    if app is not None:
        from services.family_activity_store import FamilyActivityStore
        from services.family_activity_service import FamilyActivityService
        monkeypatch.setattr(app, 'family_activities', FamilyActivityService(
            FamilyActivityStore(tmp_path / 'lifecycle-activities.json'),
            __import__('types').SimpleNamespace(list=lambda: app.family_members.list(), actor=lambda user: app.family_members.actor(user))))

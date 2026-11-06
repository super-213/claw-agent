import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from services.family_activity_privacy import cleanup_activity_history, sanitize_activity_history


def test_cleanup_skips_appledouble_but_scrubs_real_documents(tmp_path):
    runs_dir = tmp_path / 'runs'
    sessions_dir = tmp_path / 'sessions'
    for directory in (runs_dir, sessions_dir):
        directory.mkdir()
        (directory / '._record.json').write_bytes(b'\x00\x05\x16\x07\xff')
        (directory / 'record.json').write_text(json.dumps({'resource': {'id': 'gone'}, 'text': 'private fixture'}))
    service = SimpleNamespace(store=SimpleNamespace(private_unavailable=lambda: {'gone'}))
    runs = SimpleNamespace(root_dir=runs_dir, _lock=nullcontext())
    conversations = SimpleNamespace(root_dir=sessions_dir, _session_lock=lambda _: nullcontext(),
        _write_session=lambda sid, data: (sessions_dir / f'{sid}.json').write_text(json.dumps(sanitize_activity_history(data, {'gone'}))))
    cleanup_activity_history(service, runs, conversations)
    for directory in (runs_dir, sessions_dir):
        assert json.loads((directory / 'record.json').read_text())['destroyed']
        assert 'private fixture' not in (directory / 'record.json').read_text()
        assert (directory / '._record.json').read_bytes() == b'\x00\x05\x16\x07\xff'
    (runs_dir / 'broken.json').write_bytes(b'\xff')
    with pytest.raises(UnicodeDecodeError):
        cleanup_activity_history(service, runs, conversations)

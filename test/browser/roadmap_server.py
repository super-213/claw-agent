"""Isolated browser acceptance environment; no real accounts or files."""
import os
import runpy
import tempfile
from pathlib import Path
root = Path(tempfile.mkdtemp(prefix='claw-roadmap-browser-'))
os.environ['USER_FILE'] = str(root / 'users.json')
os.environ['CONVERSATION_DIR'] = str(root / 'conversations')
os.environ['RUN_DIR'] = str(root / 'runs')
os.environ['MCP_CONFIG'] = ''
runpy.run_path(str(Path(__file__).with_name('home_workbench_server.py')), run_name='__main__')

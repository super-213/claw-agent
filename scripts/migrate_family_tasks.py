#!/usr/bin/env python3
"""Preview by default. Bind accounts explicitly before applying the migration."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.home_service import HomeDataService
from services.user_store import UserStore
from services.family_member_service import FamilyMemberService
from services.family_task_service import FamilyTaskService
from services.task_store import TaskStore
from services.task_migration import TaskMigration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home-dir', default='.data/home')
    parser.add_argument('--users', default='.data/users.json')
    parser.add_argument('--timezone', default='Asia/Shanghai')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback')
    parser.add_argument('--writes-paused', action='store_true')
    args = parser.parse_args()
    root = Path(args.home_dir)
    # Avoid HomeDataService initialization: preview must not create or prune source files.
    home = object.__new__(HomeDataService)
    home.root_dir = root
    home.timezone_name = args.timezone
    members = FamilyMemberService(home, UserStore(args.users))
    service = FamilyTaskService(TaskStore(root / 'tasks.json'), members, timezone_name=args.timezone)
    migration = TaskMigration(service)
    if args.rollback:
        result = migration.rollback(args.rollback, apply=args.apply, writes_paused=args.writes_paused)
    else:
        result = migration.execute() if args.apply else migration.plan()[0]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

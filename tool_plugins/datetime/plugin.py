"""Reviewed time capability, available in CLI and Web without extra grants."""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from agent_runtime.models import ToolDefinition


def datetime_now(args):
    timezone = str(args.get('timezone') or 'Asia/Shanghai')
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f'unknown_timezone:{timezone}') from exc
    now = datetime.now(zone)
    return {'iso': now.isoformat(), 'date': now.date().isoformat(), 'timezone': timezone}


class DatetimePlugin:
    def tools(self, context):
        return [ToolDefinition(name='datetime_now',
            description='Return the current date and time in an IANA timezone.',
            input_schema={'type': 'object', 'properties': {'timezone': {'type': 'string', 'maxLength': 100}},
                          'additionalProperties': False},
            handler=datetime_now, idempotent=True, max_retries=1)]


def create_plugin():
    return DatetimePlugin()

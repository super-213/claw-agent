"""The literal ASCII spaces in '/ ' and '@ ' are part of the grammar."""
from copy import deepcopy
import re
from services.task_store import TaskError

COMMANDS = {
    '日程': ('personal', 'timed'), '备忘': ('personal', 'undated'),
    '家庭日程': ('household', 'timed'), '家庭备忘': ('household', 'undated'),
}
COMMAND_RE = re.compile(r'^/ (家庭日程|家庭备忘|日程|备忘)(?: |$)')
TIME_TEXT = re.compile(r'今天|明天|后天|下周|本周|每周|每天|每月|周[一二三四五六日天]|\d{4}-\d{2}-\d{2}|\d+月\d+[日号]')


def mention_boundary(raw, position):
    if position and not raw[position - 1].isspace():
        return False
    quote = None
    closing = {'"': '"', "'": "'", '“': '”', '‘': '’', '`': '`'}
    for index, char in enumerate(raw[:position]):
        if quote:
            if char == quote:
                quote = None
        elif char in closing and (char in {'`', '“', '‘'} or index == 0 or raw[index - 1].isspace()):
            quote = closing[char]
    return quote is None


def normalize_invocation(raw, invocation=None):
    match = COMMAND_RE.match(raw)
    if invocation is None:
        if not match:
            return None
        invocation = {'command': match[1], 'space_type': COMMANDS[match[1]][0],
                      'temporal_type': COMMANDS[match[1]][1], 'mentions': [], 'actionable': True}
    if not isinstance(invocation, dict) or invocation.get('command') not in COMMANDS:
        raise TaskError('invalid_invocation')
    value = deepcopy(invocation)
    space, temporal = COMMANDS[value['command']]
    if value.get('space_type') != space or value.get('temporal_type') != temporal:
        raise TaskError('invocation_conflict')
    if not match or match[1] != value['command']:
        raise TaskError('invocation_conflict', '原始指令必须保留带半角空格的命令前缀。')
    mentions = value.get('mentions', [])
    if (not isinstance(mentions, list) or any(not isinstance(m, dict) or not isinstance(m.get('start'), int)
            or not isinstance(m.get('end'), int) or not isinstance(m.get('label'), str)
            or not isinstance(m.get('member_id'), str) for m in mentions)):
        raise TaskError('invalid_mentions')
    tags = []
    position = match.end()
    while position < len(raw):
        if not raw.startswith('@ ', position) or not mention_boundary(raw, position):
            position += 1
            continue
        selected = next((m for m in mentions if m['start'] == position), None)
        if selected:
            label = selected['label']
            end = position + len('@ ' + label)
            if (not label or '\n' in label or selected['end'] != end or raw[position:end] != '@ ' + label
                    or (end < len(raw) and not raw[end].isspace())):
                raise TaskError('invalid_mentions', '成员标签与正文不一致，请重新选择。')
        else:
            token = re.match(r'@ ([^\s@]+)', raw[position:])
            if not token:
                raise TaskError('unresolved_mentions', '请从候选列表中选择成员标签。')
            label, end = token[1], position + token.end()
        tags.append((position, end, label))
        position = end
    if len(tags) != len(mentions) or any(m['start'] != t[0] for m, t in zip(mentions, tags)):
        raise TaskError('unresolved_mentions', '请从候选列表中选择成员标签。', candidates=[t[2] for t in tags])
    ids = [m['member_id'] for m in mentions]
    if len(set(ids)) != len(ids):
        raise TaskError('duplicate_members')
    body = raw[match.end():]
    for start, end, _label in reversed(tags):
        body = body[:start - match.end()] + body[end - match.end():]
    value['mentions'] = mentions
    value['body'] = body.strip()
    value.setdefault('actionable', True)
    value.setdefault('completion_mode', 'all')
    return value

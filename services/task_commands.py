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

# Slash commands are shortcuts. Scope is inferred only from the user's text,
# never from model-supplied identities or an arbitrary model-supplied scope.
CREATE_TEXT = re.compile(r'记一下|记下|记一条|记个|记住|记上|记着|记得|记录|加一条|加个|建一条|建个|添加|新增|创建|安排|登记|保存|存一下|提醒我|叫我|提醒我们|提醒全家|别忘了|不要忘了')
FUTURE_TEXT = re.compile(r'明天|后天|[今明][早晚]|下[周个月年]|本周|这周|周末|每[周天日月年]|周[一二三四五六日天]|\d{4}-\d{2}-\d{2}|\d+月\d+[日号]|\d+[点时]|\d{1,2}:\d{2}')
HOUSEHOLD_TEXT = re.compile(r'家庭(?:日程|备忘|共享)|(?:给|为|帮)(?:全家|家人).{0,6}(?:记|添|创|安|存)|全家(?:人)?(?:可见|共享|一起|的日程|的备忘)|(?:共享给|分享给|让)(?:全家|家人)|提醒(?:全家|我们)')
ACTION_TEXT = re.compile(r'^(?:要|需要)?(?:购买|买|领取|取|缴费|交|归还|还|打扫|清理|整理|联系|修理|更换|洗|预约|提交|准备|检查)(?!了|过)')


def infer_task_invocation(raw, temporal_type=None):
    """Resolve a natural-language creation request; ambiguous facts stay with the LLM.

    temporal_type is provided by a native creation tool after semantic intent
    recognition. The early router only handles clear task/date expressions.
    """
    raw = (raw or '').strip()
    if not raw or raw.startswith(('/', '`', '“', '"', '‘', "'")):
        return None
    if re.search(r'^(?:请问|想问|如何|怎么|怎样|如果|假如|假设)|(?:如何|怎么|怎样).{0,8}(?:创建|添加|保存|记录|安排)|(?:不要(?!忘了)|不用|别(?!忘了)|无需|不需要).{0,8}(?:记|添加|创建|保存|安排|提醒)', raw):
        return None
    if re.search(r'^(?:查看|查询|看看|列出|有没有|是否|是不是)|(?:创建|保存|添加)(?:成功|好了|好|过|了)?(?:吗|了吗|没)', raw):
        return None
    create = CREATE_TEXT.search(raw)
    if not create:
        return None
    task_words = re.search(r'日程|备忘|待办|提醒|叫我|别忘了|不要忘了', raw)
    future = FUTURE_TEXT.search(raw)
    if temporal_type is None and not task_words and re.search(r'已经|昨天|前天|上周|去年|[买交换修取做]了|换过|买过|完成了', raw):
        return None
    actionable = ACTION_TEXT.search(raw[create.end():].lstrip('：:，, \n'))
    if not task_words and not future and not actionable and temporal_type is None:
        return None
    if not task_words and not future and re.search(r'已经|昨天|前天|上周|去年|过了|换过|买过|完成了', raw):
        return None
    temporal = ('timed' if '日程' in raw else 'undated' if '备忘' in raw else
                temporal_type or ('timed' if future or '今天' in raw else 'undated'))
    space = 'household' if HOUSEHOLD_TEXT.search(raw) else 'personal'
    if re.search(r'仅(?:我|自己)|只(?:给我|自己|我可见)|个人(?:日程|备忘)|不要共享|不用共享', raw):
        space = 'personal'
    command = ('家庭' if space == 'household' else '') + ('日程' if temporal == 'timed' else '备忘')
    return {'command': command, 'space_type': space, 'temporal_type': temporal,
            'mentions': [], 'actionable': True, 'completion_mode': 'all',
            'body': raw, 'selection_source': 'natural_language'}


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

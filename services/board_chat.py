"""User-selected board audience and verifiable chat receipts."""
from copy import deepcopy
import json
import re
from services.task_store import TaskError
from services.task_commands import mention_boundary

BOARD_INTENT = re.compile(r'便[笺签]|留言板|留(?:个|一[张条个])?言|留条')
PUBLISH_INTENT = re.compile(r'发布|发(?:给|到|一?[张条])|共享|分享|贴(?:到|在|上|一?[张条])|留(?:个|一?[张条个])?(?:便[笺签]|言)|保存|确定|确认')
NEGATIVE_INTENT = re.compile(r'^(?:@\s+\S+\s*)*(?:请|我)?(?:不要|不用|无需|如果|假如)')


def instruction_text(raw):
    return re.sub(r'“[^”]*”|‘[^’]*’|"[^"]*"|`[^`]*`', '', raw)


def audience_from_text(raw, members, user):
    """Only exact, unambiguous names chosen in the user's own instruction grant sharing."""
    # Only explicit instruction text grants an audience. Quoted note bodies
    # (including @ 所有人 inside them) are data, not sharing instructions.
    instruction = instruction_text(raw)
    household_requested = bool(re.search(r'(?:给|向|让|和|与).{0,5}(?:所有人|全家|全体)|全家(?:可见|共享)|(?:分享|共享|发布)(?:给|到)?(?:全家|所有人)', instruction))
    ids = []
    # Mentions terminate at whitespace/@/punctuation. Quoted email addresses and
    # arbitrary model IDs do not become recipients.
    for match in re.finditer(r'@ +([^\s@，。,:：]+)', raw):
        if not mention_boundary(raw, match.start()):
            continue
        label = match.group(1)
        if label == '所有人':
            return {'audience_mode': 'household', 'recipient_ids': []}
        matches = members.resolve(label, user)
        if len(matches) != 1:
            raise TaskError('board_member_ambiguous', '接收人不明确，请在卡片中选择。')
        ids.append(matches[0]['member_id'])
    if not ids and household_requested:
        return {'audience_mode': 'household', 'recipient_ids': []}
    if not ids:
        labels = []
        for m in members.list():
            if m['status'] == 'active':
                labels.extend([m['display_name'], *(m.get('aliases') or []), *(m.get('speaker_aliases') or {}).keys()])
        for label in sorted(set(labels), key=len, reverse=True):
            if label and re.search(r'(?:给|告诉|向|和|、)' + re.escape(label) + r'(?:留|发|写|说|分享|共享|和|、|[，。\s]|$)', instruction):
                matches = members.resolve(label, user)
                if len(matches) == 1:
                    ids.append(matches[0]['member_id'])
    return {'audience_mode': 'selected', 'recipient_ids': list(dict.fromkeys(ids))}


def guard_board_answer(content, messages, context, retries=0, results=None):
    if results is None:
        start = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user'), -1)
        results = []
        for m in messages[start + 1:]:
            if m.get('role') == 'tool' and str(m.get('name', '')).startswith('family_board_'):
                try:
                    results.append(json.loads(m.get('content') or '{}'))
                except (ValueError, TypeError):
                    pass
    board_results = [r for r in results if str(r.get('name', '')).startswith('family_board_')]
    mutations = [r for r in board_results if r.get('name') in {'family_board_post_create', 'family_board_post_update', 'family_board_post_withdraw', 'family_board_draft_update'}]
    if mutations:
        successful = [r for r in mutations if r.get('status') == 'success']
        if successful:
            output = successful[-1].get('output') or {}
            post = output.get('post') or {}
            if output.get('mode') == 'draft':
                return '便笺草稿已准备好，尚未发布。可在下方配置内容、接收人和有效期，再点击“发布便笺”。', None
            if post.get('state') == 'withdrawn':
                return '便笺已撤下。', None
            return '便笺已保存，可在下方继续调整，也可在留言板查看；共享范围内的成员打开留言板即可看到。', None
        return '便笺尚未保存：' + str((mutations[-1].get('output') or {}).get('message') or mutations[-1].get('error') or '请在卡片中检查配置后重试。'), None
    raw = context.get('raw_input', '')
    if not BOARD_INTENT.search(raw) or not re.search(r'写|发|留|创建|帮|保存', raw) or re.search(r'不要|不用|如何|怎么|如果|吗[？?]?$', raw):
        return content, None
    if retries < 2:
        return content, '用户要求创建便笺。请调用 family_board_post_create；缺少配置返回草稿卡片，不要只用文字声称已经发布。'
    return '便笺尚未保存，本次没有收到成功结果。请重试或在留言板点击“写便笺”。', None


def current_board_context(messages, service, user, context_provider=None):
    result = deepcopy(messages)
    for message in result:
        if message.get('role') != 'tool' or not str(message.get('name', '')).startswith('family_board_'):
            continue
        # Historical model context must not retain revoked body/asset snapshots.
        try:
            envelope = json.loads(message.get('content') or '{}')
            output = envelope.get('output') or {}
            resource = output.get('resource')
            if resource:
                current = service.get(user, resource['id'], draft=resource['type'] == 'board_post_draft',
                                      context=context_provider() if context_provider else None)
                envelope['output'] = current
            else:
                envelope['output'] = {'message': '历史列表仅供来源定位，请重新调用便笺工具获取当前授权结果。'}
            message['content'] = json.dumps(envelope, ensure_ascii=False)
        except (ValueError, TypeError, KeyError, TaskError):
            message['content'] = json.dumps({'status': 'unavailable', 'message': '该便笺已不可访问，请重新查询。'}, ensure_ascii=False)
    return result

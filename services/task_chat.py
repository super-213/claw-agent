"""Ground chat creation receipts in this turn's native tool results."""
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from services.task_commands import infer_task_invocation

CREATE_TOOLS = {'family_timed_memo_create', 'family_undated_memo_create'}


def current_creation_results(messages):
    start = next((i for i in range(len(messages) - 1, -1, -1)
                  if messages[i].get('role') == 'user'), -1)
    results = []
    for message in messages[start + 1:]:
        if message.get('role') != 'tool' or message.get('name') not in CREATE_TOOLS:
            continue
        try:
            result = json.loads(message.get('content') or '{}')
        except (ValueError, TypeError):
            continue
        if isinstance(result, dict):
            results.append(result)
    return results


def creation_receipt(tasks, member_names=None):
    member_names = member_names or {}
    lines = ['已保存以下事项：']
    for task in tasks:
        kind = ('家庭' if task['space_type'] == 'household' else '个人') + ('日程' if task['temporal_type'] == 'timed' else '备忘')
        title = task['title'].replace('\n', ' ')
        when = task.get('due_at') or task.get('due_date')
        if task.get('due_at'):
            when = datetime.fromisoformat(task['due_at']).astimezone(ZoneInfo(task.get('timezone', 'Asia/Shanghai'))).strftime('%Y-%m-%d %H:%M')
        rule = task.get('recurrence')
        if rule:
            weekday = dict(zip(('MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'), '一二三四五六日')).get(rule.get('weekday'))
            when = '每周' + (weekday or '内任选时间，周日截止')
        line = f"- {title}｜{kind}" + (f"｜{when}" if when else '｜无日期')
        assignees = task.get('assignee_ids') or []
        if assignees:
            line += '｜负责人：' + '、'.join(member_names.get(mid, '家庭成员') for mid in assignees)
            if len(assignees) > 1:
                line += '（任一人完成即可）' if task.get('completion_mode') == 'any' else '（每人都需完成）'
        elif task.get('actionable'):
            line += '｜待认领'
        lines.append(line)
    lines.append('可在家庭的事项清单中查看；带日期的日程也会显示在工作台日历中。')
    return '\n'.join(lines)


def guard_task_answer(content, messages, context, retries=0, member_names=None, saved_tasks=None, creation_results=None):
    """Return (verified content, optional retry feedback), without executing writes."""
    results = current_creation_results(messages) if creation_results is None else creation_results
    tasks = {}
    for result in results:
        if result.get('status') == 'success':
            for task in (result.get('output') or {}).get('tasks', []):
                tasks[task['id']] = task
    if saved_tasks is not None:
        tasks = {task['id']: task for task in saved_tasks} if any(result.get('status') == 'success' for result in results) else {}
    if tasks:
        receipt = creation_receipt(tasks.values(), member_names)
        # A mixed fact-and-task request must retain its separately verified
        # knowledge receipt. Its finalizer runs before this guard.
        start = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user'), -1)
        if any(m.get('name') in {'knowledge_record_save', 'knowledge_document_save'} for m in messages[start + 1:]):
            return content + '\n\n' + receipt, None
        failures = [str((result.get('output') or {}).get('message') or result.get('error') or '创建失败')
                    for result in results if result.get('status') != 'success']
        if failures:
            receipt += '\n另有创建操作未保存：' + '；'.join(dict.fromkeys(failures))
        return receipt, None
    if results:
        output = results[-1].get('output') or {}
        reason = output.get('message') or results[-1].get('error') or '创建工具未返回成功结果，请重试。'
        return '事项尚未保存。' + str(reason), None
    invocation = context.get('invocation')
    raw = context.get('raw_input', '')
    claim = re.search(r'(?:已|成功).{0,16}(?:创建|添加|保存|记入|安排).{0,20}(?:日程|备忘|事项|待办)|已(?:为你|帮你)?记下', content)
    expected = bool(invocation) and not context.get('task_ref') and not re.search(r'修改|改成|改为|更改|删除|归档|取消|撤销|标记.{0,5}完成', raw)
    if not expected and not infer_task_invocation(raw, 'undated'):
        return content, None
    if not expected and not claim:
        return content, None
    # Knowledge and unrelated file saves are not task creations.
    if not expected and not re.search(r'日程|备忘|事项|待办', content):
        return content, None
    if not claim and re.search(r'哪天|几点|什么时间|具体日期|补充.{0,8}(?:日期|时间|内容)|(?:日期|时间).{0,8}(?:是|呢|？|\?)', content) and not re.search(r'/\s*日程|显式|标签', content):
        return content, None
    if not retries:
        return '', ('本轮没有成功的事项创建工具回执，不能声称已创建或已保存。'
                    '用户已授权的自然语言记录请求无需斜杠标签或再次确认；请现在调用对应创建工具，'
                    '日期/内容缺失时仅询问缺失字段。有待补充草稿时保留原时间，不能凭旧回复假报成功。')
    return '事项尚未保存：本次没有收到成功的创建结果。请补充事项内容或日期后重试。', None

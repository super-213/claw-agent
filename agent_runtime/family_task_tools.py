"""Per-run task tools. Identity and selected command never come from model arguments."""
from copy import deepcopy
from datetime import timedelta
import json
import re
from services.task_access import can_read
from services.task_store import TaskError
from .models import ToolDefinition


ITEM_SCHEMA = {'type': 'object', 'properties': {
    'title': {'type': 'string', 'minLength': 1, 'maxLength': 500},
    'description': {'type': 'string'}, 'category': {'type': 'string'},
    'due_date': {'type': ['string', 'null']}, 'due_at': {'type': ['string', 'null']},
    'starts_on': {'type': ['string', 'null']}, 'recurrence': {'type': ['object', 'null']}},
    'required': ['title'], 'additionalProperties': False}


def register_family_task_tools(registry, service, user_provider, context_provider):
    def execute(name, args):
        user = user_provider()
        actor = service.members.actor(user)
        context = context_provider()
        # Persisted run context is reauthenticated on every call, including recovery.
        if context.get('user_id') != user['id']:
            raise TaskError('run_identity_mismatch', status=403)
        session = context.get('session') or {}
        shared = (session.get('sharing') or {}).get('scope', 'private') != 'private'
        if session.get('owner_user_id') and session['owner_user_id'] != user['id']:
            shared = True
        invocation = context.get('invocation')
        if name.endswith('_memo_create') and not invocation:
            from services.task_commands import infer_task_invocation
            invocation = infer_task_invocation(context.get('raw_input', ''),
                'timed' if name == 'family_timed_memo_create' else 'undated')
        def protect_private():
            if shared:
                raise TaskError('private_session_required', '请进入个人会话处理私人事项。', status=403)
            if context.get('protect_private_session'):
                context['protect_private_session']()
        if shared:
            # Conservative first version: only household records may enter shared history.
            if name in {'family_timed_memo_create', 'family_undated_memo_create'}:
                if not invocation or invocation['space_type'] != 'household':
                    raise TaskError('private_session_required', '请进入自己的个人会话处理私人事项。', status=403)
            elif name == 'family_task_list':
                if args.get('view', 'mine') != 'household':
                    raise TaskError('private_session_required', '请进入个人会话查看私人清单。', status=403)
            elif args.get('task_id') and args['task_id'] != 'recent':
                if service.get(user, args['task_id'])['task']['visibility'] != 'household':
                    raise TaskError('private_session_required', '请进入个人会话处理私人事项。', status=403)
        session_id = context.get('session_id', '')
        branch = context.get('branch_id', '')
        ref_key = json.dumps([session_id, branch, actor])
        def remember(task_ids):
            with service.store.transaction() as doc:
                doc['references'][ref_key] = {'task_ids': list(dict.fromkeys(task_ids)), 'expires_at':
                    (service.now() + timedelta(hours=1)).isoformat(), 'user_message_id': context.get('user_message_id')}

        task_id = args.get('task_id')
        if task_id == 'recent' and context.get('task_ref'):
            task_id = context['task_ref']['task_id']
        if task_id == 'recent':
            with service.store.transaction() as doc:
                reference = doc['references'].get(ref_key, {})
                if reference.get('expires_at', '') < service.now().isoformat():
                    raise TaskError('task_reference_expired')
                source_message = reference.get('user_message_id')
                if source_message and source_message not in context.get('active_message_ids', []):
                    raise TaskError('task_reference_expired', '来源消息不在当前分支，请重新选择事项。')
                ids = reference.get('task_ids', [])
                if len(ids) != 1:
                    candidates = [{'id': t, 'title': doc['tasks'][t]['title']} for t in ids
                                  if t in doc['tasks'] and can_read(doc['tasks'][t], actor)]
                    raise TaskError('ambiguous_task', '请选择具体事项。', candidates=candidates)
                task_id = ids[0]
            if shared and service.get(user, task_id)['task']['visibility'] != 'household':
                raise TaskError('private_session_required', status=403)
        if shared and task_id and service.get(user, task_id)['task']['visibility'] != 'household':
            raise TaskError('private_session_required', status=403)
        if task_id and service.get(user, task_id)['task']['visibility'] != 'household':
            protect_private()
        if name.endswith('_memo_create') and (not invocation or invocation.get('space_type') == 'personal'):
            protect_private()
        if name in {'family_task_draft_get', 'family_task_draft_discard'}:
            with service.store.transaction() as doc:
                draft = doc['drafts'].get(ref_key)
                if (not draft or draft['expires_at'] < service.now().isoformat()
                        or (draft.get('user_message_id') and draft['user_message_id'] not in context.get('active_message_ids', []))):
                    raise TaskError('draft_not_found', status=404)
                if (draft.get('invocation') or {}).get('space_type') != 'household':
                    protect_private()
                if name == 'family_task_draft_discard':
                    doc['drafts'].pop(ref_key)
                    return {'discarded': True}
                return deepcopy(draft)
        if name == 'family_member_resolve':
            return {'candidates': service.members.resolve(args['text'], user)}
        if name == 'family_task_list':
            result = service.list(user, **args)
            if any(row['task']['visibility'] != 'household' for row in result['items']):
                protect_private()
            remember([row['task']['id'] for row in result['items']])
            return result
        if name == 'family_task_get':
            result = service.get(user, task_id)
            remember([task_id])
            return result
        request_id = context.get('request_id')
        index = args.get('operation_index', 0)
        if name.endswith('_memo_create'):
            temporal = 'timed' if name == 'family_timed_memo_create' else 'undated'
            pending = context.get('pending_draft')
            if pending and (pending.get('expires_at', '') < service.now().isoformat()
                    or (pending.get('user_message_id') and pending['user_message_id'] not in context.get('active_message_ids', []))):
                raise TaskError('draft_not_found', '草稿已过期或不在当前分支，请重新提供事项。', status=404)
            if pending and invocation and not invocation.get('body'):
                args['items'] = deepcopy(pending['items'])
            if not invocation:
                # A draft is durable but is never counted as a task.
                with service.store.transaction() as doc:
                    doc['references'].pop(ref_key, None)
                    doc['drafts'][ref_key] = {'items': args['items'], 'expires_at':
                        (service.now() + timedelta(minutes=30)).isoformat(), 'user_id': user['id'],
                        'user_message_id': context.get('user_message_id')}
                raise TaskError('explicit_selection_required', '请选择 / 日程、/ 备忘、/ 家庭日程 或 / 家庭备忘后保存。', draft=args['items'])
            if temporal != invocation['temporal_type']:
                raise TaskError('invocation_conflict')
            # A model cannot erase an undecided date expression by cleaning a memo title.
            from services.task_commands import TIME_TEXT
            if temporal == 'undated' and TIME_TEXT.search(invocation.get('body', '')) and not invocation.get('literal_time_text'):
                raise TaskError('memo_time_choice_required', '请选择转为日程或仅作为文字保存。', draft=args['items'])
            try:
                result = service.create(user, args['items'], invocation, request_id=request_id,
                    operation_index=index, source={k: context.get(k) for k in
                        ('raw_input', 'session_id', 'branch_id', 'user_message_id', 'run_id')})
            except TaskError as error:
                if error.code in {'schedule_date_required', 'unsupported_recurrence', 'memo_time_choice_required', 'member_unavailable'}:
                    with service.store.transaction() as doc:
                        doc['drafts'][ref_key] = {'items': args['items'], 'invocation': invocation,
                            'expires_at': (service.now() + timedelta(minutes=30)).isoformat(), 'user_id': user['id'],
                            'user_message_id': context.get('user_message_id')}
                raise
            with service.store.transaction() as doc:
                doc['drafts'].pop(ref_key, None)
        else:
            action = name.removeprefix('family_task_')
            if shared and action == 'update' and (args.get('patch') or {}).get('space_type') == 'personal':
                raise TaskError('private_session_required', '移动到个人空间请进入个人会话。', status=403)
            if action == 'update' and (args.get('patch') or {}).get('space_type') == 'personal':
                protect_private()
            if action == 'update':
                patch = args.get('patch') or {}
                original = service.get(user, task_id)['task']
                for field in ('space_type', 'temporal_type', 'completion_mode'):
                    if field in patch and patch[field] != original[field]:
                        recurrence_conversion = (field == 'temporal_type' and patch[field] == 'timed'
                            and patch.get('recurrence') and context.get('explicit_recurrence_update'))
                        if not recurrence_conversion and (not invocation or patch[field] != invocation.get(field)):
                            raise TaskError('explicit_update_selection_required', '请显式选择修改后的空间、性质或完成规则。')
                if 'assignee_ids' in patch and patch['assignee_ids'] != original['assignee_ids']:
                    if not invocation or patch['assignee_ids'] != [m['member_id'] for m in invocation.get('mentions', [])]:
                        raise TaskError('explicit_update_selection_required', '重新分配需要选择新的成员标签。')
                if 'recurrence' in patch and patch['recurrence'] != original['recurrence']:
                    if not context.get('explicit_recurrence_update') and not (invocation and invocation['temporal_type'] == 'timed'):
                        raise TaskError('explicit_update_selection_required', '请明确选择或说明新的周期。')
            if action in {'complete', 'reopen'}:
                original = service.get(user, task_id)['task']
                raw = context.get('raw_input', '')
                candidates = service.list(user, view='visible', query=original['title'], status='', limit=200)['items']
                matches = {row['task']['id']: row for row in candidates if row['task']['title'] == original['title']}
                if len(matches) > 1 and not context.get('task_ref') and task_id not in raw and not re.search(r'第[一二三四五六七八九十0-9]+[件条个]', raw):
                    raise TaskError('ambiguous_task', '有多个同名事项，请选择具体哪一条。', candidates=[
                        {'id': row['task']['id'], 'title': row['task']['title'], 'assignee_ids': row['task']['assignee_ids'],
                         'due_date': (row['occurrence'] or {}).get('due_date')} for row in matches.values()])
                if original['recurrence']:
                    from services.task_recurrence import monday
                    current_id = task_id + ':' + monday(service.now().date()).isoformat()
                    if args.get('occurrence_id') != current_id and not re.search(r'上周|下周|\d{4}-\d{2}-\d{2}|第.+周', raw):
                        raise TaskError('current_occurrence_required', '默认只处理本周；其他周期请明确选择。')
            result = service.change(user, task_id, action, expected_version=args['expected_version'],
                request_id=request_id, operation_index=index, occurrence_id=args.get('occurrence_id'), patch=args.get('patch'))
        remember(result['task_ids'])
        return result

    def register(name, description, properties, required=()):
        registry.register(ToolDefinition(name=name, description=description,
            input_schema={'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False},
            handler=lambda args, tool_name=name: execute(tool_name, deepcopy(args)), idempotent=True))
    register('family_task_draft_get', '读取当前说话者当前分支尚未保存的草稿，过期不可读取。', {})
    register('family_task_draft_discard', '丢弃当前说话者当前分支的待补充草稿。', {})
    register('family_member_resolve', 'Resolve a family member name; ambiguous results require a selected stable member tag.',
             {'text': {'type': 'string'}}, ['text'])
    for temporal, label in [('timed', '日程，日期或每周周期必填'), ('undated', '无时效备忘，禁止生效日期')]:
        register(f'family_{temporal}_memo_create', f'创建{label}。用户自然语言明确要求记录/安排即可调用，无需斜杠标签；默认个人，明确家庭共享时才共享。日期按本次当地时间解析，due_at 必须含时区。缺必要信息保留草稿；成功回执后才能说已保存。批量整体保存。不会通知他人。',
            {'items': {'type': 'array', 'items': ITEM_SCHEMA}, 'operation_index': {'type': 'integer'}}, ['items'])
    register('family_task_list', '从权威账本查询清单，绝不能依靠聊天记忆回答。默认我的事项；家庭共享用 household。', {
        'view': {'type': 'string', 'enum': ['mine', 'own', 'assigned', 'delegated', 'household', 'visible']},
        'space_type': {'type': 'string', 'enum': ['personal', 'household']},
        'temporal_type': {'type': 'string', 'enum': ['timed', 'undated']},
        'status': {'type': 'string'}, 'query': {'type': 'string'}, 'due_from': {'type': 'string'},
        'due_to': {'type': 'string'}, 'assignee_id': {'type': 'string'}, 'recurring': {'type': 'boolean'},
        'actionable': {'type': 'boolean'}, 'cursor': {'type': 'string'}, 'current_only': {'type': 'boolean'}})
    register('family_task_get', '查询一个授权事项及实例、历史、下期预览。recent 指代本用户本分支唯一最近事项。',
             {'task_id': {'type': 'string'}}, ['task_id'])
    for action in ('update', 'claim', 'complete', 'reopen', 'skip', 'cancel', 'pause', 'resume', 'archive', 'leave'):
        properties = {'task_id': {'type': 'string'}, 'expected_version': {'type': 'integer'},
                      'operation_index': {'type': 'integer'}}
        required = ['task_id', 'expected_version']
        if action in {'complete', 'reopen', 'skip', 'cancel'}:
            properties['occurrence_id'] = {'type': 'string'}
            required.append('occurrence_id')
        if action in {'update', 'leave', 'archive', 'skip', 'cancel'}:
            properties['patch'] = {'type': 'object'}
        register('family_task_' + action, f'对真实事项执行 {action}。需先查询当前 ID 和版本；完成仅针对本人本期，停止整个系列用 archive。每个合法写操作使用独立 operation_index，重试沿用。', properties, required)

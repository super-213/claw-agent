"""Native tools use minimal durable receipts; all private content lives in the ledger."""
from copy import deepcopy
import re
from agent_runtime.models import ToolDefinition
from agent_runtime.card_presenter import card_reference
from services.task_store import TaskError
from services.board_chat import instruction_text


def register_activity_tools(registry, service, binding, kind):
    prefix = 'family_' + kind + '_'
    label = '家庭投票' if kind == 'poll' else '家庭接龙'

    def receipt(view, context, *, include_definition=False):
        if view.get('destroyed'):
            return {'resource': view['resource'], 'destroyed': True, 'receipt': label + '已删除。',
                    'resource_changed': dict(type='resource_changed', resource_type=view['resource']['type'], resource_id=view['resource']['id'])}
        row = view['activity']
        result = dict(resource=view['resource'], mode=view['mode'], state=row['state'], version=row['version'],
                      participation_version=view['participation_version'], participant_count=len(view['participants']),
                      missing_fields=row['missing_fields'], close_reason=row['close_reason'],
                      option_ids=[o['id'] for o in row['options']], counts=row.get('counts'),
                      receipt='草稿尚未发布，请在卡片补充。' if view['mode'] == 'draft' else label + '已核实，可在卡片及留言板查看。')
        if include_definition:
            # Current field/option definitions are needed to map explicit natural-language edits and votes.
            # They remain resource-bound and are scrubbed with the same destruction policy.
            result['options'] = deepcopy(row['options'])
            result['fields'] = deepcopy(row['fields'])
        result['ui_blocks'] = [card_reference(kind, view['resource']['type'], view['resource']['id'], context=context, mode=view['mode'])]
        result['resource_changed'] = dict(type='resource_changed', resource_type=view['resource']['type'], resource_id=view['resource']['id'])
        return result

    def execute(action, args):
        user, context = binding.get_user(), binding.get_execution_context()
        if not user or context.get('user_id') != user['id']:
            raise TaskError('run_identity_mismatch', status=403)
        service.context(context, write=action not in ('get', 'list', 'draft_get'))
        if action == 'list':
            views = service.list(user, kind, context=context)
            items = [receipt(v, context) for v in views]
            return {'items': items, 'ui_blocks': [block for item in items for block in item['ui_blocks']]}
        draft = action.startswith('draft_')
        identifier = args.get('activity_id') or args.get('draft_id')
        if action in ('get', 'draft_get'):
            return receipt(service.get(user, kind, identifier, draft=draft, context=context), context, include_definition=True)
        raw = instruction_text(context.get('raw_input', ''))
        if action in ('vote', 'join', 'update_entry', 'withdraw_vote', 'withdraw_entry') and not re.search(r'投|选|报名|接龙|参加|参与|撤回|撤销|改成|改为|修改', raw):
            raise TaskError('explicit_participation_required', '代本人参与需要用户明确要求。')
        if action == 'delete' and not re.search(r'删除|销毁|不要了|移除', raw):
            raise TaskError('explicit_delete_required', '删除活动需要用户明确要求。')
        data = deepcopy(args.get('data', {}))
        request_id = str(context.get('request_id') or context.get('run_id')) + ':' + kind + ':' + action + ':' + str(args.get('operation_index', 0))
        if action == 'create':
            if not re.search(r'创建|发起|新建|发布|拟|草稿|帮.*(?:投票|接龙)', raw):
                raise TaskError('explicit_create_required', '请明确要求创建家庭活动。')
            required_times = []
            if re.search(r'参与截止|投票截止|接龙截止|截止|截至', re.sub(r'存在截止', '', raw)): required_times.append('participation_deadline_at')
            if re.search(r'保留|存在截止|销毁|自动删除', raw) and not re.search(r'长期|永久|一直保留', raw): required_times.append('expires_at')
            data['required_time_fields'] = required_times
            if re.search(r'不要创建|不用创建', raw):
                raise TaskError('explicit_create_required')
            draft = bool(args.get('draft')) or bool(re.search(r'拟|草稿|先写|不发布|不发出', raw))
            try:
                view = service.create(user, kind, data, request_id=request_id, draft=draft, context=context)
            except TaskError as exc:
                if exc.code != 'activity_fields_required':
                    raise
                view = service.create(user, kind, data, request_id=request_id, draft=True, context=context)
        else:
            mapped = {'update': 'save', 'draft_update': 'publish' if args.get('publish') else 'save_draft',
                      'vote': 'participate', 'join': 'participate', 'update_entry': 'participate',
                      'withdraw_vote': 'withdraw', 'withdraw_entry': 'withdraw'}.get(action, action)
            view = service.change(user, kind, identifier, mapped, data=data, request_id=request_id,
                expected_version=args.get('expected_version'), participation_version=args.get('participation_version'), draft=draft, context=context)
        return receipt(view, context)

    props = {'title': {'type': 'string'}, 'description': {'type': 'string'},
             **{k: {'type': ['string', 'null'], 'description': '带时区的 ISO 时间；不设置则为 null。'} for k in ('participation_deadline_at', 'expires_at')},
             **{k: {'type': ['number', 'null']} for k in ('participation_duration_hours', 'retention_duration_hours')},
             'auto_close': {'type': 'boolean'}, 'notify_creator': {'type': 'boolean'}}
    if kind == 'poll':
        props.update(options={'type': 'array', 'items': {'type': 'object', 'properties': {'id': {'type': 'string'}, 'text': {'type': 'string'}}, 'required': ['text'], 'additionalProperties': False}},
                     multiple={'type': 'boolean'}, min_choices={'type': 'integer'}, max_choices={'type': 'integer'}, allow_change={'type': 'boolean'})
    else:
        props.update(capacity={'type': ['integer', 'null']}, fields={'type': 'array', 'items': {'type': 'object', 'properties': {
            'id': {'type': 'string'}, 'label': {'type': 'string'}, 'type': {'type': 'string', 'enum': ['text', 'number']}, 'required': {'type': 'boolean'}},
            'required': ['id', 'label', 'type', 'required'], 'additionalProperties': False}})
    definition = {'type': 'object', 'properties': props, 'additionalProperties': False}

    def register(action, description, properties, required=()):
        registry.register(ToolDefinition(name=prefix + action, description=description,
            input_schema={'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False},
            handler=lambda args, selected=action: execute(selected, args), replay_policy='revalidate', idempotent=True))
    operation = {'operation_index': {'type': 'integer', 'description': '同一请求内多个操作使用不同索引。'}}
    identity = {'activity_id': {'type': 'string'}, **operation}
    version = {'expected_version': {'type': 'integer'}}
    register('create', '创建' + label + '并发布到家庭留言板，家人均可参与。标题必填，投票至少两个选项；信息不足或仅代写时返回交互草稿。参与截止与存在截止独立，后者到期销毁；默认全员（含创建者）参与后结束并提醒创建者。时间不得猜测，明确相对时长可用 duration_hours。返回最小回执与卡片，内容以卡片为准。', {'data': definition, 'draft': {'type': 'boolean'}, **operation}, ['data'])
    register('list', '查询当前家庭活动，返回每项可点击的真实交互卡片，不根据历史猜测活动仍存在。', {})
    register('get', '查看真实活动卡片、版本、当前选项 ID 与文字、接龙字段定义及统计。按查询到的真实 ID 映射用户指定选项，不按序号猜测；参与明细在卡片展示。', identity, ['activity_id'])
    register('update', '按真实 ID 和版本修改原活动；已有参与后题目及参与规则冻结，结束后不可重开。', {**identity, **version, 'data': definition}, ['activity_id', 'expected_version', 'data'])
    for action in ('close', 'delete'):
        register(action, ('主动结束' if action == 'close' else '用户明确要求时永久删除') + label + '，仅创建者可操作；删除不可恢复。', {**identity, **version}, ['activity_id', 'expected_version'])
    for action in ('draft_get', 'draft_update'):
        register(action, '读取或补充当前用户原分支活动草稿；publish=true 才提交发布。', {'draft_id': {'type': 'string'}, **version, 'data': definition, 'publish': {'type': 'boolean'}, **operation}, ['draft_id'] + (['expected_version', 'data'] if action.endswith('update') else []))
    participating = {'type': 'object', 'properties': {'option_ids': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['option_ids'], 'additionalProperties': False} if kind == 'poll' else {'type': 'object', 'properties': {'values': {'type': 'object', 'description': '字段 ID 到文字或数字；默认字段为 content。'}}, 'required': ['values'], 'additionalProperties': False}
    for action in (('vote', 'withdraw_vote') if kind == 'poll' else ('join', 'update_entry', 'withdraw_entry')):
        register(action, '仅在用户明确要求时提交、修改或撤回当前用户本人的参与；不能代其他成员操作。', {**identity, 'participation_version': {'type': 'integer'}, 'data': participating}, ['activity_id', 'participation_version'] + ([] if action.startswith('withdraw') else ['data']))


class ActivityExtension:
    def __init__(self, context, kind):
        self.context, self.kind = context, kind

    def selected(self):
        runtime = self.context.services['runtime']()
        return (runtime.run or {}).get('family_task_context') or runtime.family_task_context or {}

    def system_messages(self):
        return [{'role': 'system', 'content': '家庭投票与接龙使用 family_poll_* / family_relay_* 原生工具并返回交互卡片，不能作为便笺或事项。明确创建家庭活动即发布给当前家庭；只拟稿或缺字段返回未发布草稿。参与截止只结束参与，存在截止销毁。仅按用户明确要求代本人参与，禁止替全家投票／报名。详情在卡片，文字仅给简短真实回执。'}]

    def normalize_response(self, content, calls):
        if any(call.name.startswith('family_' + self.kind + '_') for call in calls):
            return '正在核实家庭活动。'
        return content

    def defer_output(self):
        return ('投票' if self.kind == 'poll' else '接龙') in self.selected().get('raw_input', '')

    def validate_answer(self, content, messages, retries):
        runtime = self.context.services['runtime']()
        prefix = 'family_' + self.kind + '_'
        results = [step['tool_result'] for step in (runtime.run or {}).get('steps', []) if (step.get('tool_result') or {}).get('name', '').startswith(prefix)]
        if results:
            last = results[-1]
            if last.get('status') == 'success':
                output = last.get('output') or {}
                return output.get('receipt', '已核实家庭活动，请在卡片中查看。'), None
            return '操作未完成：' + str(last.get('error') or '请检查活动权限、时间与版本后重试。'), None
        raw = self.selected().get('raw_input', '')
        if self.defer_output() and re.search(r'创建|发起|发布|删除|修改|销毁', raw) and not re.search(r'如何|怎么|不要|不用|计划|方案', raw):
            return ('', '请先调用家庭活动工具并核实持久化结果。') if retries < 2 else ('尚未收到家庭活动工具的成功结果，请重试。', None)
        return content, None

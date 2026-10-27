"""Native board tools, bound to the authenticated speaker and active branch."""
from copy import deepcopy
from services.board_chat import audience_from_text, BOARD_INTENT, PUBLISH_INTENT, NEGATIVE_INTENT, instruction_text
from services.task_store import TaskError
from .models import ToolDefinition
from .card_presenter import card_reference
import re


def register_family_board_tools(registry, service, user_provider, context_provider, resolve_source):
    def execute(name, args):
        user, context = user_provider(), context_provider()
        if context.get('user_id') != user['id']:
            raise TaskError('run_identity_mismatch', status=403)
        session = context.get('session') or {}
        context['shared'] = ((session.get('sharing') or {}).get('scope', 'private') != 'private'
                             or session.get('owner_user_id') != user['id'])
        service._context({}, context, write=name not in {'family_board_post_get', 'family_board_post_list', 'family_board_draft_get'})
        raw = context.get('raw_input', '')
        instruction = instruction_text(raw)
        request_id = str(context.get('request_id')) + ':board:' + str(args.get('operation_index', 0))
        if name == 'family_board_post_list':
            return service.list(user, cursor=args.get('cursor'), context=context)
        draft = name.startswith('family_board_draft_')
        resource_id = args.get('post_id') or args.get('draft_id')
        if resource_id == 'recent':
            resource_type = 'board_post_draft' if draft else 'board_post'
            active = context.get('active_message_ids', [])
            refs = []
            for message in session.get('messages', []):
                if message.get('node_id') not in active:
                    continue
                blocks = [b['resource']['id'] for b in message.get('ui_blocks', [])
                          if b.get('kind') == 'board_post' and (b.get('resource') or {}).get('type') == resource_type]
                if blocks:
                    refs = list(dict.fromkeys(blocks))
            if len(refs) != 1:
                raise TaskError('ambiguous_board_post', '请在卡片中选择具体便笺。')
            resource_id = refs[0]
        if name in {'family_board_post_get', 'family_board_draft_get'}:
            result = service.get(user, resource_id, draft=draft, context=context)
        elif name == 'family_board_post_withdraw':
            if not re.search(r'撤下|撤回|删除|收回', raw):
                raise TaskError('explicit_withdraw_required', '撤下便笺需要用户明确要求。')
            result = service.change(user, resource_id, {}, request_id=request_id, expected_version=args['expected_version'], action='withdraw', context=context)
        else:
            data = deepcopy(args.get('data') or {})
            if not isinstance(data, dict):
                raise TaskError('invalid_board_fields')
            creating = name == 'family_board_post_create'
            if creating and NEGATIVE_INTENT.search(instruction.strip()):
                raise TaskError('board_intent_required', '用户没有要求实际创建便笺。')
            if creating and not (BOARD_INTENT.search(raw) or raw.lstrip().startswith('@ ')):
                raise TaskError('board_intent_required', '请先明确要求写便笺。')
            if creating or {'audience_mode', 'recipient_ids'} & data.keys():
                try:
                    audience = audience_from_text(raw, service.members, user)
                except TaskError:
                    if not creating:
                        raise
                    audience = {'audience_mode': 'selected', 'recipient_ids': []}
                if not creating and audience == {'audience_mode': 'selected', 'recipient_ids': []}:
                    raise TaskError('explicit_audience_required', '请在卡片中选择新的共享对象。')
                data.update(audience)
            if creating:
                # Body dates alone do not create expiration; explicit retention does.
                if re.search(r'长期|永久|一直保留', instruction):
                    data.update(retention_mode='permanent', expires_at=None, duration_hours=None)
                elif re.search(r'保留(?:到|至|\s*\d)|截止|有效期|到期|限时', instruction):
                    data['retention_mode'] = 'until'
                else:
                    data.update(retention_mode='permanent', expires_at=None, duration_hours=None)
            sources = args.get('image_paths') or []
            if sources:
                selected = {m.get('path') or m.get('url'): m for m in context.get('knowledge_media', [])
                            if m.get('node_id') == context.get('user_message_id')}
                blocks = list(data.get('content_blocks', []))
                for source in sources:
                    media = selected.get(source)
                    if not media:
                        raise TaskError('source_attachment_not_found', '只能使用本次选定的真实附件。')
                    path = resolve_source(user, source, context['session_id'], media['node_id'])
                    if path.stat().st_size > 10 * 1024 * 1024:
                        raise TaskError('board_image_too_large', '单张图片不能超过 10MiB。', status=413)
                    asset = service.upload(user, path.read_bytes())
                    blocks.append({'type': 'image', 'asset_id': asset['asset_id'], 'alt': media.get('name', '')})
                data['content_blocks'] = blocks
            if creating:
                publish = bool(PUBLISH_INTENT.search(instruction)) and not re.search(r'先写|先拟|草稿|暂不发布|不要发布|不发布', instruction)
                if publish:
                    try:
                        result = service.create(user, data, request_id=request_id, context=context)
                    except TaskError as error:
                        if error.code != 'board_fields_required':
                            raise
                        result = service.create(user, data, request_id=request_id, draft=True, context=context)
                else:
                    result = service.create(user, data, request_id=request_id, draft=True, context=context)
            else:
                action = ('publish' if args.get('publish') and PUBLISH_INTENT.search(instruction) else 'save_draft') if draft else 'save'
                result = service.change(user, resource_id, data, request_id=request_id, expected_version=args['expected_version'],
                                        draft=draft, action=action, context=context)
        resource = result['resource']
        result['ui_blocks'] = [card_reference('board_post', resource['type'], resource['id'], context=context, mode=result['mode'])]
        return result

    def register(name, description, properties, required=()):
        registry.register(ToolDefinition(name=name, description=description,
            input_schema={'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False},
            handler=lambda args, tool_name=name: execute(tool_name, deepcopy(args)), idempotent=True))
    block = {'type': 'object', 'properties': {'type': {'type': 'string', 'enum': ['text', 'image']},
             'text': {'type': 'string'}, 'asset_id': {'type': 'string'}, 'alt': {'type': 'string'}}, 'required': ['type'], 'additionalProperties': False}
    data = {'type': 'object', 'properties': {'title': {'type': 'string'}, 'content_blocks': {'type': 'array', 'items': block},
            'retention_mode': {'type': 'string', 'enum': ['permanent', 'until']}, 'expires_at': {'type': ['string', 'null']},
            'duration_hours': {'type': ['number', 'null']}, 'audience_mode': {'type': 'string', 'enum': ['selected', 'household']},
            'recipient_ids': {'type': 'array', 'items': {'type': 'string'}}}, 'additionalProperties': False}
    create_data = deepcopy(data)
    create_data['properties']['content_blocks'] = {'type': 'array', 'items': {'type': 'object', 'properties': {
        'type': {'type': 'string', 'enum': ['text']}, 'text': {'type': 'string'}}, 'required': ['type', 'text'], 'additionalProperties': False}}
    register('family_board_post_create', '为留言板创建图文便笺。data.content_blocks 只传文字块；新图没有 asset_id，必须把真实当前附件的 path 传入 image_paths，服务端会导入图片。共享对象从用户原话中的 @ 成员/所有人或给谁解析，不能擅自公开。明确发布且字段齐全则发布，否则返回可配置草稿。截止时间必须带时区，相对保留用 duration_hours；正文中活动时间不是便笺截止时间。成功后才可声称保存。',
             {'data': create_data, 'image_paths': {'type': 'array', 'items': {'type': 'string'}}, 'operation_index': {'type': 'integer'}}, ['data'])
    register('family_board_post_list', '查询自己创建、别人@自己和@所有人的有效便笺，自动合并展示；到期便笺已销毁，不提供历史筛选，不得根据旧回复推断仍可见。',
             {'cursor': {'type': 'string'}})
    for draft in (False, True):
        prefix, identifier = ('family_board_draft_', 'draft_id') if draft else ('family_board_post_', 'post_id')
        register(prefix + 'get', '查询本账号授权便笺或原分支草稿。recent 表示本分支最近唯一引用。', {identifier: {'type': 'string'}}, [identifier])
        register(prefix + 'update', '按真实 ID 和版本修改原便笺/草稿，禁止另建副本。共享范围只取用户明确选择；过期不可修改。',
                 {identifier: {'type': 'string'}, 'expected_version': {'type': 'integer'}, 'data': data,
                  'publish': {'type': 'boolean'}, 'operation_index': {'type': 'integer'}}, [identifier, 'expected_version', 'data'])
    register('family_board_post_withdraw', '用户明确要求时撤下自己的有效便笺，需真实 ID 和版本，不删除聊天或其他业务记录。',
             {'post_id': {'type': 'string'}, 'expected_version': {'type': 'integer'}, 'operation_index': {'type': 'integer'}}, ['post_id', 'expected_version'])

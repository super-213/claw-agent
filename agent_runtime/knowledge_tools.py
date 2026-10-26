"""Library tools bound to authenticated actor, active session and explicit intent."""
import re
from .models import ToolDefinition
from services.task_store import TaskError


def register_knowledge_tools(registry, service, user_provider, context_provider, resolve_file):
    def context():
        user, ctx = user_provider(), context_provider()
        if not user or ctx.get('user_id') != user['id']:
            raise TaskError('run_identity_mismatch', status=403)
        session = ctx.get('session') or {}
        if ((session.get('sharing') or {}).get('scope', 'private') != 'private'
                or session.get('owner_user_id') != user['id']):
            raise TaskError('private_session_required', '请在自己的个人会话中查询和保存资料与记忆。', status=403)
        if ctx.get('protect_private_session'):
            ctx['protect_private_session']()
        return user, ctx

    def execute(name, args):
        user, ctx = context()
        raw = ctx.get('raw_input', '')
        if name == 'knowledge_search':
            return service.search(user, args['query'], limit=5, identity=args.get('identity'))
        if name == 'knowledge_get':
            row = service.get(user, args['collection'], args['identity'])
            row['history'] = row.get('history', [])[-5:]
            if len(row.get('content', '')) > 3000:
                row['content'] = row['content'][:3000]
                row['notice'] = '记录过长，仅预览开头；具体问题请检索或读取来源片段。'
            return row
        if name == 'knowledge_source':
            return service.source(user, args['collection'], args['identity'], args['version'], args.get('chunk', 0))
        request_id = f"{ctx.get('request_id')}:{name}:{args.get('operation_index', 0)}"
        if name in {'knowledge_document_save', 'knowledge_record_save'}:
            if not re.search(r'记[下住一]|记一下|帮我记|保存|存[一下起]|留[下存]', raw):
                raise TaskError('explicit_save_required', '先询问用户是否保存，不能自动保留对话内容。')
            if name == 'knowledge_document_save':
                candidates = ctx.get('knowledge_media', [])
                selected = [m for m in candidates if args.get('path') in {m.get('path'), m.get('url')}]
                if len(selected) != 1:
                    raise TaskError('attachment_selection_required', '请选择当前对话中的具体附件。')
                selected = selected[0]
                source = {'type': 'chat', 'session_id': ctx.get('session_id'),
                    'node_id': selected.get('node_id'), 'filename': selected.get('name')}
                return service.save_document(user, resolve_file(user, args['path']), request_id=request_id,
                    title=args.get('title', ''), object_name=args.get('object_name', ''), source=source)
            if args.get('kind') != 'preference' and re.search(r'提醒|待办|明天|后天|下周|每[天周月]|[一二三四五六七八九十\d]+[天周个月年]后', args['content']):
                raise TaskError('task_selection_required', '未来安排请使用事项工具与草稿选择；已发生的事实可单独记录。')
            return service.save_record(user, request_id=request_id, title=args['title'], content=args['content'],
                kind=args.get('kind', 'fact'), object_name=args.get('object_name', ''),
                source={'type': 'chat', 'session_id': ctx.get('session_id'), 'node_id': ctx.get('user_message_id'), 'text': raw})
        if not re.search(r'改|更[正新]|纠正|过时|作废|失效|换|撤', raw):
            raise TaskError('explicit_update_required', '请先获得用户明确的更正或更新要求。')
        patch = args['patch']
        if 'visibility' in patch:
            raise TaskError('explicit_sharing_required', '共享范围请在资料或记忆管理中明确选择。')
        return service.change(user, args['collection'], args['identity'], patch,
            expected_version=args['expected_version'], request_id=request_id)

    def register(name, description, fields, required):
        registry.register(ToolDefinition(name=name, description=description,
            input_schema={'type': 'object', 'properties': fields, 'required': required, 'additionalProperties': False},
            handler=lambda args, n=name: execute(n, args), timeout=180, idempotent=True))

    string = {'type': 'string'}
    collection = {'type': 'string', 'enum': ['documents', 'records']}
    register('knowledge_search', '搜索已保存的资料、说明书、家庭信息和偏好。涉及以前记录或家中设备时先检索；返回来源链接与时间，未命中不得猜测。',
        {'query': string, 'identity': string}, ['query'])
    register('knowledge_get', '读取真实资料或记忆的元数据、当前版本和更新记录；更新前必须先读取。',
        {'collection': collection, 'identity': string}, ['collection', 'identity'])
    register('knowledge_source', '读取指定当前版本的原文片段。来源与历史记录有时效，失效后重新检索。',
        {'collection': collection, 'identity': string, 'version': {'type': 'integer'}, 'chunk': {'type': 'integer'}},
        ['collection', 'identity', 'version'])
    register('knowledge_document_save', '用户明确要求保存时，将当前对话的真实附件保存为个人资料。只能从运行时附件清单选择 path；区分 ready/partial/failed，失败不能声称已可检索。',
        {'path': string, 'title': string, 'object_name': string, 'operation_index': {'type': 'integer'}}, ['path'])
    register('knowledge_record_save', '用户明确要求记住时，保存家庭事实、发生记录或个人偏好。保留原始来源。待办/提醒必须使用事项创建工具，支持自然语言创建，缺必要信息才保留草稿；不用此工具代替事项；含未来安排时分别处理。相同对象更正先查询，再 update，避免重复事实。',
        {'title': string, 'content': string, 'kind': {'type': 'string', 'enum': ['fact', 'event', 'preference']},
         'object_name': string, 'operation_index': {'type': 'integer'}}, ['title', 'content'])
    register('knowledge_update', '按用户明确要求更正记录或标记过时，先读取真实 ID 与 version。新增发生事件用 save，不覆盖旧事件。共享范围由管理界面选择。',
        {'collection': collection, 'identity': string, 'expected_version': {'type': 'integer'},
         'patch': {'type': 'object'}, 'operation_index': {'type': 'integer'}}, ['collection', 'identity', 'expected_version', 'patch'])

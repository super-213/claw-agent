import json

class Extension:
    def __init__(self, context):
        self.context = context

    def selected_context(self):
        runtime = self.context.services['runtime']()
        return (runtime.run or {}).get('family_task_context') or runtime.family_task_context or {}

    def system_messages(self):
        task_context = self.selected_context()
        dynamic_system = []
        if task_context:
            dynamic_system.append({'role': 'system', 'content':
                '本次事项选择（标签或用户自然语言，服务端确定的空间和性质不得覆盖）：' + json.dumps(task_context.get('invocation'), ensure_ascii=False) +
                '\n本次当地时间：' + str(task_context.get('as_of')) +
                '\n用户自然语言明确要求记录/安排/提醒即可创建，无需输入 / 标签或重复确认。默认个人；只有明确要求家庭共享才用家庭空间。'
                '例如“帮我记一下，明天这个时候叫我去上海”应直接调用 family_timed_memo_create。'
                'due_at 使用带时区的 ISO 时间；“明天此时”依据本次当地时间，缺少日期才询问。'
                '\n事项必须调用 family_task 工具查询或执行。只有本轮创建工具成功返回才可说已保存，历史回复不是保存证据。'
                '保存后立即可见，不是到期才显示。每周完成仅完成本期；不发送消息或通知。'})
            if task_context.get('pending_draft'):
                dynamic_system.append({'role': 'system', 'content': '用户正在接续本分支待保存草稿，原日期和内容如下，请调用创建工具保存，不重复要求标签：' +
                    json.dumps(task_context['pending_draft'], ensure_ascii=False)})
        if task_context and task_context.get('object_context'):
            dynamic_system.append({'role': 'system', 'content':
                '用户从家庭视图选择的对象（仅为定位数据，所有读取和写入仍需工具校验权限）：' +
                json.dumps(task_context['object_context'], ensure_ascii=False)})
        return dynamic_system

    def defer_output(self):
        from services.task_commands import CREATE_TEXT
        ctx = self.selected_context()
        return bool(ctx.get('invocation') or ctx.get('pending_draft') or CREATE_TEXT.search(ctx.get('raw_input', '')))

    def validate_answer(self, content, messages, retries):
        from services.task_chat import guard_task_answer, CREATE_TOOLS
        runtime = self.context.services['runtime']()
        run = runtime.run or {}
        service = self.context.services['family_tasks']
        context = self.selected_context()
        results = [step['tool_result'] for step in run.get('steps', [])
                   if (step.get('tool_result') or {}).get('name') in CREATE_TOOLS]
        saved = None
        if any(result.get('status') == 'success' for result in results):
            saved = service.created_in_request(self.context.get_user(), context.get('request_id') or run.get('id'))
        return guard_task_answer(content, messages, context, retries, saved_tasks=saved, creation_results=results,
            member_names={m['member_id']: m['display_name'] for m in service.members.list()})

    def normalize_response(self, content, calls):
        from services.task_chat import CREATE_TOOLS
        return '' if any(call.name in CREATE_TOOLS for call in calls) else content

    def resource_events(self, result):
        change = result.output.get('task_changed') if result.success and isinstance(result.output, dict) else None
        return [change, {'type': 'resource_changed', 'resource_type': 'family_task',
                 'resource_ids': change['task_ids'], 'revision': change['revision']}] if change else []

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
                '便笺/留言板与日程备忘是独立业务。写便笺使用 family_board_post_create；'
                '图文、接收人、长期或限时通过交互卡片配置。@ 成员表示接收范围；@ 所有人仅表示当前家庭。'
                '只代写或字段不足时返回未发布草稿；明确发布且信息完整时直接发布。'
                '以 @ 成员开头的“我要……”若没有明确日程/备忘意图，调用便笺创建工具返回待配置草稿。'
                '正文中的聚餐等时间不是便笺到期；只有明确保留到/有效期才配置截止。'
                '不要把便笺创建为事项，不得用旧历史声称仍可见。收到工具成功结果后才能说已保存，不会发送通知。'})
        return dynamic_system

    def defer_output(self):
        from services.board_chat import BOARD_INTENT
        raw = self.selected_context().get('raw_input', '')
        return bool(BOARD_INTENT.search(raw) or raw.lstrip().startswith('@ '))

    def filter_context(self, messages):
        from services.board_chat import current_board_context
        return current_board_context(messages, self.context.services['board'],
                                     self.context.get_user(), self.context.get_execution_context)

    def validate_answer(self, content, messages, retries):
        from services.board_chat import guard_board_answer
        runtime = self.context.services['runtime']()
        results = [s['tool_result'] for s in (runtime.run or {}).get('steps', [])
                   if str((s.get('tool_result') or {}).get('name', '')).startswith('family_board_')]
        return guard_board_answer(content, messages, self.selected_context(), retries, results=results)

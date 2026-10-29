from services.knowledge_context import has_knowledge, fresh_knowledge_context

class Extension:
    def __init__(self, context):
        self.context = context

    def preserve_history(self, messages):
        return has_knowledge(messages)

    def avoid_memory(self, messages):
        return has_knowledge(messages)

    def prepare_history(self, messages):
        return fresh_knowledge_context(messages)

    def filter_context(self, messages):
        return self.context.services['knowledge'].current_tool_context(messages, self.context.get_user())

    def finalize_answer(self, content, messages):
        return self.context.services['knowledge'].finalize_answer(self.context.get_user(), content, messages)

    def defer_output(self):
        runtime = self.context.services['runtime']()
        return has_knowledge(runtime.conversation.get_messages())

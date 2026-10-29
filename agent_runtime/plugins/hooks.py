"""Deterministic extension dispatch; all security filters compose, never override."""
class RuntimeHooks:
    def __init__(self):
        self._entries = []

    @property
    def extensions(self):
        return [entry[2] for entry in sorted(self._entries, key=lambda entry: entry[:2])]

    def add(self, extension, priority=0):
        self._entries.append((priority, len(self._entries), extension))

    def any(self, method, *args):
        return any(getattr(ext, method)(*args) for ext in self.extensions if hasattr(ext, method))

    def transform(self, method, value, *args):
        for ext in self.extensions:
            if hasattr(ext, method):
                value = getattr(ext, method)(value, *args)
        return value

    def collect(self, method, *args):
        result = []
        for ext in self.extensions:
            if hasattr(ext, method):
                result.extend(getattr(ext, method)(*args))
        return result

    def validate_answer(self, content, messages, retries):
        for ext in self.extensions:
            if hasattr(ext, 'validate_answer'):
                content, feedback = ext.validate_answer(content, messages, retries)
                if feedback:
                    return content, feedback
        return content, None

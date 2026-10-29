"""File authority bound by the host; canonicalize before checking ownership."""
from pathlib import Path
from agent_runtime import builtin_tools as io
from services.media_input import MediaInputReader


class FileToolAccess:
    def __init__(self, project, generated, *, protected_paths=(), user_id=None,
                 get_user=lambda: None, authorize_generated=None, grants=None, execution_context=lambda: {}):
        self.project, self.generated = Path(project).resolve(), Path(generated).resolve()
        self.protected = protected_paths
        self.user_id, self.get_user = user_id, get_user
        self.authorize_generated, self.grants = authorize_generated, grants
        self.execution_context = execution_context
        self.output = self.generated / user_id if user_id else self.generated
        self.output.mkdir(parents=True, exist_ok=True)

    def read(self, args):
        source = str(args['path'])
        raw = Path(source)
        if source.startswith(('/generated/', '/files/')):
            local = MediaInputReader(self.generated).local_path(source)
        else:
            local = (raw if raw.is_absolute() else self.project / raw).resolve()
            if not raw.is_absolute() and not local.exists():
                local = (self.output / raw).resolve()
        if self.authorize_generated and self.generated in local.parents:
            self.authorize_generated(self.get_user(), local)
        return io._file_read({**args, 'path': str(local)}, (self.project, self.generated), self.protected)

    def write(self, args):
        result = io._file_write(args, self.output)
        session_id = self.execution_context().get('session_id')
        if self.grants is not None and session_id:
            with self.grants.transaction() as doc:
                doc.setdefault('file_grants', {})[str(Path(result['path']).resolve())] = {
                    'owner_user_id': self.user_id, 'session_id': session_id}
        if self.user_id:
            result['url'] = '/generated/' + str(Path(result['path']).relative_to(self.generated))
        return result

    def needs_approval(self, args):
        return io._file_write_needs_approval(args, self.output)

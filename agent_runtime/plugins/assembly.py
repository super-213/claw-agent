"""Shared Web/CLI host-service assembly. No tool names or schemas here."""
from .access import FileToolAccess


def foundation_services(*, registry, project_root, generated_files_dir, executor,
                        skill_registry=None, home_assistant_service=None, browser_handler=None,
                        app_handler=None, allowed_http_domains=(), protected_paths=(), family_mode=False,
                        files=None):
    from agent_runtime import builtin_tools as io
    result = {
        'registry': registry,
        'files': files or FileToolAccess(project_root, generated_files_dir, protected_paths=protected_paths),
        'public_http': lambda args: io._http_request(args, allowed_http_domains),
        'allowed_http_domains': allowed_http_domains, 'executor': executor,
        'family_mode': family_mode, 'browser_handler': browser_handler, 'app_handler': app_handler,
    }
    if skill_registry is not None:
        result['skills'] = skill_registry
        from skills.installer import SkillInstaller
        result['skill_installer'] = SkillInstaller(skill_registry,
            lambda args: io._http_request(args, allowed_http_domains, max_response_chars=2 * 1024 * 1024))
    if home_assistant_service is not None:
        result['home_assistant'] = home_assistant_service
    return result

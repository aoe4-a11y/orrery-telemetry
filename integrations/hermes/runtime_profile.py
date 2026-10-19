"""Process-local config overlay; memory, sessions and skills stay profile scoped."""
from pathlib import Path


def config_path(config):
    return Path(config.get('runtime_config') or Path(config['profile_home']) / 'config.yaml')


def install(config):
    target = config_path(config).resolve(strict=True)
    if not config.get('runtime_config'):
        return
    # Import config only after HERMES_HOME is pinned. Patch the path resolver,
    # rather than its merged loader, so defaults/cache/security logic survive.
    import hermes_constants
    hermes_constants.get_config_path = lambda: target
    from hermes_cli import config as module
    module.get_config_path = lambda: target


def require_prepared(config):
    """Read the pinned PM selection; never invoke recovery or dependency install."""
    from hermes_cli._early_recovery import _missing_environment
    from pm.environments import committed_venv, runtime_facts_path
    source = Path(config['hermes_source'])
    environment = committed_venv(source)
    if (environment is None or environment.resolve() != Path(config['hermes_python']).parent.parent.resolve()
            or _missing_environment(source)
            or any(path.exists() for path in (source / '.update-incomplete', source / '.lazy-refresh-incomplete',
                                               runtime_facts_path(source).parent / '.repair-incomplete'))):
        raise ValueError('Managed Hermes dependencies require explicit operator repair')


def isolate_tool_profiles(config):
    """Keep native indirect lookups inside this profile, including embedded IDs."""
    from tools import session_search_tool, skill_manager_tool
    def current(profile):
        if profile not in (None, '', config['profile_name']):
            raise ValueError('Managed session search is confined to the current profile')
        return None  # Reuse the already-open current database, never open a sibling.
    session_search_tool._resolve_profile_db = current
    # Upstream's not-found hint otherwise scans sibling skill directories.
    skill_manager_tool._find_skill_in_other_profiles = lambda name: []

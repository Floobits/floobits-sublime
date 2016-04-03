import os
import stat

try:
    from urllib.parse import urlparse
    assert urlparse
except ImportError:
    from urlparse import urlparse

try:
    from . import api, msg
    from . import shared as G
    assert api and G and msg
except ImportError:
    import api
    import msg
    import shared as G


REPO_MAPPING = {
    '.git': 'git',
    '.svn': 'svn',
    '.hg': 'hg',
}


def update(workspace_url, project_dir):
    repo_type = detect_repo_type(project_dir)
    if not repo_type:
        return
    msg.debug('Detected ', repo_type, ' repo in ', project_dir)
    data = {
        'type': repo_type,
    }
    # TODO: catch?
    api.update_workspace(workspace_url, data)


def detect_repo_type(d):
    for k, v in REPO_MAPPING.items():
        repo_path = os.path.join(d, k)
        try:
            s = os.stat(repo_path)
        except Exception:
            continue
        if stat.S_ISDIR(s.st_mode):
            return v

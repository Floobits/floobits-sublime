import os
import stat
import subprocess

try:
    from . import api, msg
    from . import shared as G
    from .exc_fmt import str_e
    assert api and G and msg and str_e
except ImportError:
    import api
    import msg
    import shared as G
    from exc_fmt import str_e


REPO_MAPPING = {
    'git': {
        'dir': '.git',
        'cmd': ['git', 'remote get-url --push origin'],
    },
    'svn': {
        'dir': '.svn',
        'cmd': ['svn', ''],
    },
    'hg': {
        'dir': '.hg',
        'cmd': ['hg', ''],
    },
}


def detect_repo_type(d):
    for repo_type, v in REPO_MAPPING.items():
        repo_path = os.path.join(d, v['dir'])
        try:
            s = os.stat(repo_path)
        except Exception:
            continue
        if stat.S_ISDIR(s.st_mode):
            return repo_type


def update(workspace_url, project_dir):
    repo_type = detect_repo_type(project_dir)
    if not repo_type:
        return
    msg.debug('Detected ', repo_type, ' repo in ', project_dir)
    data = {
        'type': repo_type,
    }
    cmd = REPO_MAPPING[repo_type]['cmd']
    try:
        p = subprocess.Popen(cmd,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             cwd=project_dir)
        result = p.communicate()
        repo_url = result[0]
        msg.log(repo_type, ' url is ', repo_url)
        if not repo_url:
            return
    except Exception as e:
        msg.error('Error getting ', repo_type, ' url:', str_e(e))
        return

    data['url'] = repo_url
    # TODO: catch?
    api.update_workspace(workspace_url, data)

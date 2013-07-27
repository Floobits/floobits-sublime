import os
import fnmatch

try:
    from . import msg, shared as G, utils
    assert G and msg and utils
except ImportError:
    import msg
    import shared as G


IGNORE_FILES = ['.gitignore', '.hgignore', '.flignore', '.flooignore']
# TODO: make this configurable
HIDDEN_WHITELIST = ['.floo'] + IGNORE_FILES
# TODO: grab global git ignores:
# gitconfig_file = popen("git config -z --get core.excludesfile", "r");
DEFAULT_IGNORES = ['extern', 'node_modules', 'tmp', 'vendor']


def create_flooignore(path):
    flooignore = os.path.join(path, '.flooignore')
    # A very short race condition, but whatever.
    if os.path.exists(flooignore):
        return
    try:
        with open(flooignore, 'wb') as fd:
            fd.write('\n'.join(DEFAULT_IGNORES).encode('utf-8'))
    except Exception as e:
        msg.error('Error creating default .flooignore: %s' % str(e))


class Ignore(object):
    def __init__(self, parent, path):
        self.parent = parent
        self.ignores = {}
        self.path = utils.unfuck_path(path)
        msg.debug('Initializing ignores for %s' % path)
        for ignore_file in IGNORE_FILES:
            try:
                self.load(ignore_file)
            except:
                pass

    def load(self, ignore_file):
        with open(os.path.join(self.path, ignore_file), 'rb') as fd:
            ignores = fd.read().decode('utf-8')
        self.ignores[ignore_file] = []
        for ignore in ignores.split('\n'):
            ignore = ignore.strip()
            if len(ignore) == 0:
                continue
            if ignore[0] == '#':
                continue
            msg.debug('Adding %s to ignore patterns' % ignore)
            self.ignores[ignore_file].append(ignore)

    def is_ignored_message(self, path, pattern, ignore_file):
        return '%s ignored by pattern %s in %s' % (path, pattern, os.path.join(self.path, ignore_file))

    def is_ignored(self, path):
        rel_path = os.path.relpath(path, self.path)
        for ignore_file, patterns in self.ignores.items():
            for pattern in patterns:
                base_path, file_name = os.path.split(rel_path)
                if pattern[0] == '/':
                    if utils.unfuck_path(base_path) == self.path and fnmatch.fnmatch(file_name, pattern[1:]):
                        return self.is_ignored_message(path, pattern, ignore_file)
                else:
                    if fnmatch.fnmatch(file_name, pattern):
                        return self.is_ignored_message(path, pattern, ignore_file)
                    if fnmatch.fnmatch(rel_path, pattern):
                        return self.is_ignored_message(path, pattern, ignore_file)
        if self.parent:
            return self.parent.is_ignored(path)
        return False


def build_ignores(path):
    current_ignore = Ignore(None, G.PROJECT_PATH)
    current_path = G.PROJECT_PATH
    starting = os.path.relpath(path, G.PROJECT_PATH)
    for p in starting.split(os.sep):
        current_path = os.path.join(current_path, p)
        if p == '..':
            raise ValueError('%s is not in project path %s' % (current_path, G.PROJECT_PATH))
        current_ignore = Ignore(current_ignore, current_path)
    return current_ignore

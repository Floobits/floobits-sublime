import os
import fnmatch

try:
    from . import msg, shared as G, utils
    assert G and msg and utils
except ImportError:
    import msg
    import shared as G


IGNORE_FILES = ['.gitignore', '.hgignore', '.flignore']
# TODO: grab global git ignores:
# gitconfig_file = popen("git config -z --get core.excludesfile", "r");


class Ignore(object):
    def __init__(self, parent, path):
        self.parent = parent
        self.ignores = []
        self.path = path
        msg.debug('Initializing ignores for %s' % path)
        for ignore_file in IGNORE_FILES:
            try:
                self.load(ignore_file)
            except:
                pass

    def load(self, ignore_file):
        fd = open(os.path.join(self.path, ignore_file), 'rb')
        ignores = fd.read().decode('utf-8')
        fd.close()
        for ignore in ignores.split('\n'):
            ignore = ignore.strip()
            if len(ignore) == 0:
                continue
            if ignore[0] == '#':
                continue
            msg.debug('Adding %s to ignore patterns' % ignore)
            self.ignores.append(ignore)

    def is_ignored(self, path):
        rel_path = os.path.relpath(path, self.path)
        for pattern in self.ignores:
            base_path, file_name = os.path.split(rel_path)
            if pattern[0] == '/':
                if os.path.samefile(base_path, self.path) and fnmatch.fnmatch(file_name, pattern[1:]):
                    return True
            else:
                if fnmatch.fnmatch(file_name, pattern):
                    return True
                if fnmatch.fnmatch(rel_path, pattern):
                    return True
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

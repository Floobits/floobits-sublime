import os
import errno
import fnmatch
import stat

try:
    from . import msg, utils
    from .exc_fmt import str_e
    assert msg and str_e and utils
except ImportError:
    import msg
    from exc_fmt import str_e

try:
    unicode()
except NameError:
    unicode = str


IGNORE_FILES = ['.gitignore', '.hgignore', '.flignore', '.flooignore']
HIDDEN_WHITELIST = ['.floo'] + IGNORE_FILES
BLACKLIST = [
    '.DS_Store',
    '.git',
    '.svn',
    '.hg',
]

# TODO: grab global git ignores:
# gitconfig_file = popen("git config -z --get core.excludesfile", "r");
DEFAULT_IGNORES = [
    '#*',
    '*.o',
    '*.pyc',
    '*~',
    'extern/',
    'node_modules/',
    'tmp',
    'vendor/',
]
MAX_FILE_SIZE = 1024 * 1024 * 5

IS_IG_EXCLUDED = 0
IS_IG_IGNORED = 1
IS_IG_CHECK_CHILD = 2


class Ignore(object):
    def __init__(self, path, parent=None, recurse=True):
        self.parent = parent
        self.size = 0
        self.children = {}
        self.files = []
        self.ignores = {
            '/TOO_BIG/': []
        }
        self.path = utils.unfuck_path(path)

        if not parent:
            self.ignores['/DEFAULT/'] = BLACKLIST

        try:
            paths = os.listdir(self.path)
        except OSError as e:
            if e.errno != errno.ENOTDIR:
                msg.error('Error listing path %s: %s' % (path, str_e(e)))
            return
        except Exception as e:
            msg.error('Error listing path %s: %s' % (path, str_e(e)))
            return

        msg.debug('Initializing ignores for %s' % path)
        for ignore_file in IGNORE_FILES:
            try:
                self.load(ignore_file)
            except Exception:
                pass
        if recurse:
            for p in paths:
                self.add_file(p)

    def add_file(self, p):
        p_path = os.path.join(self.path, p)
        if p in BLACKLIST:
            msg.log('Ignoring blacklisted file %s' % p)
            return
        if p == '.' or p == '..':
            return
        try:
            s = os.stat(p_path)
        except Exception as e:
            msg.error('Error stat()ing path %s: %s' % (p_path, str_e(e)))
            return

        is_dir = stat.S_ISDIR(s.st_mode)
        if self.is_ignored(p_path, is_dir=is_dir, log=True):
            return

        if is_dir:
            ig = Ignore(p_path, self)
            self.children[p] = ig
            # self.size += ig.size
            return

        if stat.S_ISREG(s.st_mode):
            if s.st_size > (MAX_FILE_SIZE):
                self.ignores['/TOO_BIG/'].append(p)
                msg.log(self.is_ignored_message(p_path, p, '/TOO_BIG/', False))
            else:
                self.size += s.st_size
                self.files.append(p_path)

    def load(self, ignore_file):
        with open(os.path.join(self.path, ignore_file), 'r') as fd:
            ignores = fd.read()
        rules = []
        for ignore in ignores.split('\n'):
            ignore = ignore.strip()
            if len(ignore) == 0:
                continue
            if ignore[0] == '#':
                continue
            msg.debug('Adding %s to ignore patterns' % ignore)
            rules.insert(0, ignore)
        self.ignores[ignore_file] = rules

    def get_children(self):
        children = list(self.children.values())
        for c in children:
            children += c.get_children()
        return children

    def list_paths(self):
        for f in self.files:
            yield os.path.join(self.path, f)
        for c in self.children.values():
            for p in c.list_paths():
                yield p

    def is_ignored_message(self, path, pattern, ignore_file, exclude):
        exclude_msg = ''
        if exclude:
            exclude_msg = '__NOT__ '
        if ignore_file == '/TOO_BIG/':
            return '%s %signored because it is too big (more than %s bytes)' % (path, exclude_msg, MAX_FILE_SIZE)
        return '%s %signored by pattern %s in %s' % (path, exclude_msg, pattern, os.path.join(self.path, ignore_file))

    def is_ignored(self, path, is_dir=None, log=False):
        if is_dir is None:
            try:
                s = os.stat(path)
            except Exception as e:
                msg.error('Error lstat()ing path %s: %s' % (path, str_e(e)))
                return True
            is_dir = stat.S_ISDIR(s.st_mode)
        ig = self._is_ignored(path, is_dir, log)
        if ig == IS_IG_CHECK_CHILD:
            return False
        return ig

    def _is_ignored(self, path, is_dir, log):
        rel_path = os.path.relpath(path, self.path)
        if self.parent:
            ignored = self.parent._is_ignored(path, is_dir, log)
            if ignored != IS_IG_CHECK_CHILD:
                return ignored
        base_path, file_name = os.path.split(rel_path)
        for ignore_file, patterns in self.ignores.items():
            for pattern in patterns:
                orig_pattern = pattern
                exclude = False
                match = False
                if pattern[0] == "!":
                    exclude = True
                    pattern = pattern[1:]

                if pattern[0] == '/':
                    # Only match immediate children
                    if utils.unfuck_path(base_path) == self.path and fnmatch.fnmatch(file_name, pattern[1:]):
                        match = True
                else:
                    if len(pattern) > 0 and pattern[-1] == '/':
                        if is_dir:
                            pattern = pattern[:-1]
                    if fnmatch.fnmatch(file_name, pattern):
                        match = True
                    elif fnmatch.fnmatch(rel_path, pattern):
                        match = True
                if match:
                    if log:
                        msg.log(self.is_ignored_message(path, orig_pattern, ignore_file, exclude))
                    if exclude:
                        return IS_IG_EXCLUDED
                    return IS_IG_IGNORED
        return IS_IG_CHECK_CHILD


def create_flooignore(path):
    flooignore = os.path.join(path, '.flooignore')
    # A very short race condition, but whatever.
    if os.path.exists(flooignore):
        return
    try:
        with open(flooignore, 'w') as fd:
            fd.write('\n'.join(DEFAULT_IGNORES))
    except Exception as e:
        msg.error('Error creating default .flooignore: %s' % str_e(e))


def get_for_path(base_path, path):
    if not utils.is_shared(path):
        return None

    if not os.path.isdir(path):
        return None

    ig = Ignore(base_path)
    split = utils.to_rel_path(path).split('/')
    for d in split:
        if d not in ig.children:
            break
        ig = ig.children[d]

    return ig

import os
import json

import sublime

import shared as G

per_path = os.path.abspath('persistent.json')


class edit:
    def __init__(self, view):
        self.view = view

    def __enter__(self):
        self.edit = self.view.begin_edit()
        return self.edit

    def __exit__(self, type, value, traceback):
        self.view.end_edit(self.edit)


def get_full_path(p):
    full_path = os.path.join(G.PROJECT_PATH, p)
    return unfuck_path(full_path)


def unfuck_path(p):
    return os.path.normcase(os.path.normpath(p))


def to_rel_path(p):
    return p[len(G.PROJECT_PATH) + 1:]


def is_shared(p):
    p = unfuck_path(p)
    return G.PROJECT_PATH == p[:len(G.PROJECT_PATH)]


def get_persistent_data():
    try:
        per = open(per_path, 'rb')
    except (IOError, OSError):
        return {}
    try:
        persistent_data = json.loads(per.read())
    except:
        return {}
    return persistent_data


def update_persistent_data(data):
    with open(per_path, 'wb') as per:
        per.write(json.dumps(data))


def rm(path):
    """removes path and dirs going up until a OSError"""
    os.remove(path)
    try:
        os.removedirs(os.path.split(path)[0])
    except OSError as e:
        if e.errno != 66:
            sublime.error_message('Can not delete directory {0}.\n{1}'.format(path, e))
            raise


def mkdir(path):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno != 17:
            sublime.error_message('Can not create directory {0}.\n{1}'.format(path, e))
            raise

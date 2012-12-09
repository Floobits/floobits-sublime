import os
import json

import shared


class edit:
    def __init__(self, view):
        self.view = view

    def __enter__(self):
        self.edit = self.view.begin_edit()
        return self.edit

    def __exit__(self, type, value, traceback):
        self.view.end_edit(self.edit)


def get_full_path(p):
    full_path = os.path.join(shared.PROJECT_PATH, p)
    return unfuck_path(full_path)


def unfuck_path(p):
    return os.path.normcase(os.path.normpath(p))


def to_rel_path(p):
    return p[len(shared.PROJECT_PATH):]


per_path = os.path.abspath('persistent.json')


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

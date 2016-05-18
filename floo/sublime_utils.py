import sublime

try:
    from .common import msg, shared as G, utils
    assert G and msg and utils
except (ImportError, ValueError):
    from common import msg, shared as G, utils


def get_text(view):
    return view.substr(sublime.Region(0, view.size()))


def create_view(buf):
    path = utils.get_full_path(buf['path'])
    view = G.WORKSPACE_WINDOW.open_file(path)
    if view:
        msg.debug('Created view', view.name() or view.file_name())
    return view


def get_buf(view):
    if not (G.AGENT and not view.is_scratch() and view.file_name()):
        return
    return G.AGENT.get_buf_by_path(view.file_name())


def send_summon(buf_id, sel):
    highlight_json = {
        'id': buf_id,
        'name': 'highlight',
        'ranges': sel,
        'summon': True,
    }
    if G.AGENT and G.AGENT.is_ready():
        G.AGENT.send(highlight_json)


def get_view_in_group(view_buffer_id, group):
    for v in G.WORKSPACE_WINDOW.views_in_group(group):
        if view_buffer_id == v.buffer_id():
            return v

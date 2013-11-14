import os

try:
    from .common import shared as G
    assert G
except ImportError:
    from common import shared as G

G.PLUGIN_PATH = os.path.split(os.path.dirname(__file__))[0]
if G.PLUGIN_PATH in ('.', ''):
    G.PLUGIN_PATH = os.getcwd()

import os

try:
    from . import shared as G
    assert G
except ImportError:
    import shared as G

G.PLUGIN_PATH = os.path.split(os.path.dirname(__file__))[0]
if G.PLUGIN_PATH in ('.', ''):
    G.PLUGIN_PATH = os.getcwd()

try:
    from .listener import Listener
    from .agent_connection import AgentConnection
    assert AgentConnection and Listener
except ImportError:
    from listener import Listener
    from agent_connection import AgentConnection

assert AgentConnection and Listener

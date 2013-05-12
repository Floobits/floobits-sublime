try:
    from .listener import Listener
    from .agent_connection import AgentConnection
    from . import shared as G
except ImportError:
    from listener import Listener
    from agent_connection import AgentConnection
    import shared as G

assert Listener
assert AgentConnection
assert G

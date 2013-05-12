try:
    from .listener import Listener
    from .agent_connection import AgentConnection
    from . import shared as G
    assert AgentConnection and G and Listener
except ImportError:
    from listener import Listener
    from agent_connection import AgentConnection
    import shared as G

assert AgentConnection and G and Listener

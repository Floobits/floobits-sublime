import os

__VERSION__ = ''
__PLUGIN_VERSION__ = ''

# Config settings
USERNAME = ''
SECRET = ''
API_KEY = ''

DEBUG = False
SOCK_DEBUG = False

EXPERT_MODE = False

ALERT_ON_MSG = True
LOG_TO_CONSOLE = False

BASE_DIR = os.path.expanduser(os.path.join('~', 'floobits'))


# Shared globals
DEFAULT_HOST = 'floobits.com'
DEFAULT_PORT = 3448
SECURE = True

PROXY_PORT = 0  # Random port
SHARE_DIR = None
COLAB_DIR = ''
PROJECT_PATH = ''
WORKSPACE_WINDOW = None

PERMS = []
STALKER_MODE = False
SPLIT_MODE = False

AUTO_GENERATED_ACCOUNT = False
PLUGIN_PATH = None

CHAT_VIEW = None
CHAT_VIEW_PATH = None

TICK_TIME = 100
AGENT = None

IGNORE_MODIFIED_EVENTS = False
VIEW_TO_HASH = {}

FLOORC_PATH = os.path.expanduser(os.path.join('~', '.floorc'))

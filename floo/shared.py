import os


__VERSION__ = '0.03'

DEBUG = False

PLUGIN_PATH = None

JOINED_WORKSPACE = False

BASE_DIR = os.path.expanduser(os.path.join('~', 'floobits'))
COLAB_DIR = ''

PROJECT_PATH = ''
DEFAULT_HOST = 'floobits.com'
DEFAULT_PORT = 3448
SECURE = True

USERNAME = ''
SECRET = ''
API_KEY = ""

ALERT_ON_MSG = True

PERMS = []

WORKSPACE_WINDOW = None

CHAT_VIEW = None
CHAT_VIEW_PATH = None
LOG_TO_CONSOLE = False

STALKER_MODE = False

IGNORE_MODIFIED_EVENTS = False

TICK_TIME = 100
AGENT = None

VIEW_TO_HASH = {}

FLOORC_PATH = os.path.expanduser('~/.floorc')

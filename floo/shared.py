import os


# Protocol version
__VERSION__ = '0.03'

# Config settings
USERNAME = ''
SECRET = ''
API_KEY = ''

DEBUG = False
SOCK_DEBUG = False

ALERT_ON_MSG = True
LOG_TO_CONSOLE = False

BASE_DIR = os.path.expanduser(os.path.join('~', 'floobits'))


# Shared globals
DEFAULT_HOST = 'floobits.com'
DEFAULT_PORT = 3448
SECURE = True


COLAB_DIR = ''
PROJECT_PATH = ''
JOINED_WORKSPACE = False
PERMS = []
STALKER_MODE = False

AUTO_GENERATED_ACCOUNT = False
PLUGIN_PATH = None
WORKSPACE_WINDOW = None
CHAT_VIEW = None
CHAT_VIEW_PATH = None

TICK_TIME = 100
AGENT = None

IGNORE_MODIFIED_EVENTS = False
VIEW_TO_HASH = {}

FLOORC_PATH = os.path.expanduser(os.path.join('~', '.floorc'))

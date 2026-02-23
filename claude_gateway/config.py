"""Configuration for the Telegram Claude Gateway."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Default config locations (in priority order):
# 1. Environment variables (always highest priority)
# 2. .env in the current working directory
# 3. ~/.config/claude-gateway/config.env (user config from setup wizard)

_config_dir = Path.home() / ".config" / "claude-gateway"
_user_config = _config_dir / "config.env"

# Load .env from CWD first, then fall back to user config dir
load_dotenv()
if not Path(".env").exists() and _user_config.exists():
    load_dotenv(_user_config)

# Telegram Bot Token
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Allowed chat IDs (comma-separated in env)
_allowed_ids = os.getenv("ALLOWED_CHAT_IDS", "")
ALLOWED_CHAT_IDS: set[int] = set()
if _allowed_ids:
    ALLOWED_CHAT_IDS = {int(cid.strip()) for cid in _allowed_ids.split(",") if cid.strip()}

# Default project directory (used for new sessions)
DEFAULT_PROJECT_PATH = os.getenv("DEFAULT_PROJECT_PATH", str(Path.home()))

# Directories to search when using /project <name> (comma-separated in env)
_search_dirs_env = os.getenv("PROJECT_SEARCH_DIRS", "")
PROJECT_SEARCH_DIRS: list[str] = (
    [d.strip() for d in _search_dirs_env.split(",") if d.strip()]
    if _search_dirs_env
    else [str(Path.home())]
)

# Directory where /newproject creates new projects
NEW_PROJECT_DIR = os.getenv("NEW_PROJECT_DIR", str(Path.home()))

# Dashboard configuration
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "3000"))

# Data directory for agent store / history
DATA_DIR = os.getenv(
    "DATA_DIR",
    str(Path.home() / ".local" / "share" / "claude-gateway"),
)

# Streaming configuration
CHUNK_SEND_INTERVAL = 2.0  # seconds between message updates
MAX_MESSAGE_LENGTH = 4000  # Telegram limit is 4096, leave buffer

# Path to the user config file (used by setup wizard and dashboard)
CONFIG_FILE = str(_user_config)

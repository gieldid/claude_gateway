# Claude Gateway

A Telegram bot that lets you remotely control [Claude Code CLI](https://claude.ai/code) from your phone. Designed to run on a Raspberry Pi or any Linux server, it forwards your Telegram messages to Claude Code and streams responses back in real time.

```
Telegram <──> claude-gateway <──> Claude Code CLI
```

> **Dashboard:** A web dashboard for browser-based access is included but is still a **work in progress**.

---

## Features

- Send messages to Claude Code from Telegram from anywhere
- Conversations carry context automatically (uses `--continue` between messages)
- Switch between projects with `/project` or an inline keyboard
- Create new project directories with `/newproject`
- Upload images directly to your current project folder
- Cancel running Claude operations with `/stop`
- Chat ID whitelist keeps the bot private
- Interactive setup wizard (`claude-gateway setup`)
- Optional systemd service for auto-start on boot

---

## Prerequisites

1. **Claude Code CLI** installed and authenticated on the host machine:
   ```bash
   npm install -g @anthropic-ai/claude-code
   claude --version
   ```

2. **Python 3.11+** on the host machine.

3. **A Telegram bot token** — create one via [@BotFather](https://t.me/BotFather) on Telegram (`/newbot`).

4. **Your Telegram chat ID** — you can find it by messaging [@userinfobot](https://t.me/userinfobot) or by starting the bot without a whitelist and reading the ID from the unauthorized message.

---

## Installation

### Recommended: pipx (isolated environment)

```bash
pipx install claude-gateway
```

### Alternative: pip

```bash
pip install claude-gateway
```

### From source

```bash
git clone https://github.com/yourusername/claude-gateway.git
cd claude-gateway
pip install -e .
```

---

## Setup

Run the interactive wizard after installation:

```bash
claude-gateway setup
```

The wizard will ask for:

| Setting | Description |
|---|---|
| **Bot token** | The token from @BotFather |
| **Allowed chat IDs** | Comma-separated Telegram chat IDs that can use the bot |
| **Default project path** | Directory Claude opens in for each new session |
| **Project search dirs** | Comma-separated dirs scanned for the `/project` command |
| **New project dir** | Where `/newproject` creates folders |
| **Dashboard host/port** | Optional, defaults to `0.0.0.0:3000` |

Configuration is saved to `~/.config/claude-gateway/config.env`.

### Getting your chat ID

If you're not sure of your chat ID, start the bot without setting one, send any message, and the bot will reply with your ID. Then re-run `claude-gateway setup` and add it.

---

## Running the bot

```bash
claude-gateway start
```

The bot will connect to Telegram and start listening for messages.

---

## Bot commands

| Command | Description |
|---|---|
| `/start` | Welcome message and current project |
| `/help` | Show all commands |
| `/new` | Start a fresh Claude conversation |
| `/project` | Show project picker (inline keyboard) |
| `/project <name>` | Switch to a named project |
| `/newproject <name>` | Create a new project directory and switch to it |
| `/status` | Show current session info |
| `/stop` | Cancel the current Claude operation |

Any other message is forwarded directly to Claude Code.

---

## Configuration reference

All settings can be set via environment variables or in `~/.config/claude-gateway/config.env`:

```env
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Security: comma-separated chat IDs allowed to use the bot
ALLOWED_CHAT_IDS=123456789,987654321

# Project directories
DEFAULT_PROJECT_PATH=/home/user/projects
PROJECT_SEARCH_DIRS=/home/user/projects,/mnt/ssd/projects
NEW_PROJECT_DIR=/home/user/projects

# Dashboard (optional, work in progress)
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=3000

# Data storage for the dashboard agent store
DATA_DIR=/home/user/.local/share/claude-gateway
```

Environment variables always take precedence over the config file. A `.env` file in the current working directory takes precedence over `~/.config/claude-gateway/config.env`.

---

## Running as a systemd service

Generate service files with:

```bash
claude-gateway systemd
```

This creates `claude-gateway.service` and `claude-dashboard.service` in the current directory. Install them:

```bash
sudo cp claude-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now claude-gateway
```

Check status and logs:

```bash
sudo systemctl status claude-gateway
journalctl -u claude-gateway -f
```

---

## Dashboard (Work in Progress)

A web dashboard is included that provides browser-based access to Claude via agents. It is currently a **work in progress** and may have rough edges.

To start it:

```bash
claude-gateway dashboard
```

Then open `http://localhost:3000` in your browser.

The dashboard exposes a REST + WebSocket API (`/api/*`) and a React frontend (if the frontend has been built). The frontend source is in the `frontend/` directory.

---

## Security

- **Chat ID whitelist**: Only configured chat IDs can interact with the bot. Anyone else receives an unauthorized message showing their chat ID.
- **Path validation**: The bot blocks access to sensitive system directories (`/etc`, `/root`, `/var`, `/usr`, `/bin`, `/sbin`, `/boot`).
- **`--dangerously-skip-permissions`**: Claude Code runs without interactive permission prompts since there is no TTY. Access control is delegated to the Telegram whitelist and path validation.
- **Config file permissions**: The setup wizard creates `~/.config/claude-gateway/config.env` with mode `0600` (owner read/write only).

---

## Project structure

```
claude_gateway/
├── cli.py           # CLI entry point (setup, start, dashboard, systemd)
├── config.py        # Configuration loading
├── gateway.py       # Telegram bot handlers
├── claude_runner.py # Claude Code process manager
├── dashboard.py     # FastAPI dashboard (WIP)
├── agent_store.py   # JSON persistence for dashboard agents
└── models.py        # Pydantic data models
```

---

## License

MIT

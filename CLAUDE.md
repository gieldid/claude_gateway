# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram Gateway for Claude Code - a Python bot that allows remote interaction with Claude Code CLI on a Raspberry Pi via Telegram.

## Commands

```bash
# Run the bot
./venv/bin/python gateway.py

# Install dependencies
./venv/bin/pip install -r requirements.txt

# Install as systemd service
sudo cp systemd/claude-gateway.service /etc/systemd/system/
sudo systemctl enable claude-gateway
sudo systemctl start claude-gateway
```

## Architecture

```
Telegram <-> gateway.py <-> claude_runner.py <-> Claude Code CLI
```

**Three-module design:**
- `gateway.py` - Telegram bot handlers, message routing, session management per chat
- `claude_runner.py` - Async wrapper around `claude --print` CLI, manages process lifecycle
- `config.py` - Environment-based configuration (bot token, allowed chat IDs, paths)

**Message flow:**
1. User sends Telegram message
2. `is_authorized()` validates chat ID against whitelist
3. `ClaudeRunner.run()` spawns `claude --print "<message>"` in session's working directory
4. Output streamed back via Telegram message edits (chunks every 2s or 1000 chars)
5. Long responses split at 4000 chars into multiple messages

**Session state (in-memory per chat_id):**
- `working_dir` - Current project directory for Claude context

**Security:**
- Chat ID whitelist in `ALLOWED_CHAT_IDS` env var
- Path validation blocks `/etc`, `/root`, `/var`, `/usr`, `/bin`, `/sbin`, `/boot`

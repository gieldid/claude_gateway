"""Web dashboard for Claude Code Gateway - FastAPI application."""

import asyncio
import json
import logging
import os

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agent_store import store
from .claude_runner import ClaudeRunner
from dotenv import set_key
from .config import (
    DASHBOARD_HOST, DASHBOARD_PORT, PROJECT_SEARCH_DIRS,
    NEW_PROJECT_DIR, BOT_TOKEN, DEFAULT_PROJECT_PATH, CONFIG_FILE,
)
from . import config as _config
from .models import AgentCreate, AgentUpdate, Message

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Claude Gateway Dashboard")

# Dashboard gets its own runner instance (separate from Telegram)
runner = ClaudeRunner()


# --- REST API ---

@app.get("/api/projects")
def list_projects():
    """List all projects from PROJECT_SEARCH_DIRS."""
    projects = []
    for search_dir in PROJECT_SEARCH_DIRS:
        if not os.path.isdir(search_dir):
            continue
        for entry in sorted(os.listdir(search_dir)):
            full = os.path.join(search_dir, entry)
            if os.path.isdir(full):
                projects.append({"name": entry, "path": os.path.realpath(full)})
    return projects


@app.post("/api/projects", status_code=201)
def create_project(data: dict):
    """Create a new project directory in NEW_PROJECT_DIR."""
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid project name")
    project_path = os.path.join(NEW_PROJECT_DIR, name)
    if os.path.exists(project_path):
        raise HTTPException(status_code=400, detail=f"Project '{name}' already exists")
    try:
        os.makedirs(project_path)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to create project: {e}")
    return {"name": name, "path": os.path.realpath(project_path)}


# --- Config ---

@app.get("/api/config")
def get_config():
    """Return current Telegram/gateway configuration."""
    token = BOT_TOKEN
    if token:
        masked = "****" + token[-6:] if len(token) > 6 else "****"
    else:
        masked = "(not set)"
    return {
        "bot_token_masked": masked,
        "allowed_chat_ids": sorted(_config.ALLOWED_CHAT_IDS),
        "project_search_dirs": PROJECT_SEARCH_DIRS,
        "new_project_dir": NEW_PROJECT_DIR,
        "default_project_path": DEFAULT_PROJECT_PATH,
    }


@app.post("/api/config/chat-ids")
def add_chat_id(data: dict):
    """Add a chat ID to the Telegram whitelist."""
    try:
        chat_id = int(data.get("chat_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="chat_id must be an integer")
    _config.ALLOWED_CHAT_IDS.add(chat_id)
    _write_chat_ids()
    return {"allowed_chat_ids": sorted(_config.ALLOWED_CHAT_IDS)}


@app.delete("/api/config/chat-ids/{chat_id}")
def remove_chat_id(chat_id: int):
    """Remove a chat ID from the Telegram whitelist."""
    if chat_id not in _config.ALLOWED_CHAT_IDS:
        raise HTTPException(status_code=404, detail="Chat ID not found")
    _config.ALLOWED_CHAT_IDS.discard(chat_id)
    _write_chat_ids()
    return {"allowed_chat_ids": sorted(_config.ALLOWED_CHAT_IDS)}


def _write_chat_ids():
    """Persist ALLOWED_CHAT_IDS back to the config file."""
    value = ",".join(str(cid) for cid in sorted(_config.ALLOWED_CHAT_IDS))
    set_key(CONFIG_FILE, "ALLOWED_CHAT_IDS", value)


@app.get("/api/agents")
def list_agents():
    """List all agents."""
    agents = store.list_agents()
    # Add running status
    result = []
    for a in agents:
        d = a.model_dump()
        d["is_running"] = runner.is_running(a.id)
        result.append(d)
    return result


@app.post("/api/agents", status_code=201)
def create_agent(data: AgentCreate):
    """Create a new agent."""
    # Validate project path
    valid, result = runner.validate_path(data.project_path)
    if not valid:
        raise HTTPException(status_code=400, detail=result)
    data.project_path = result
    agent = store.create_agent(data)
    return agent.model_dump()


@app.patch("/api/agents/{agent_id}")
def update_agent(agent_id: str, data: AgentUpdate):
    """Update an agent."""
    if data.project_path is not None:
        valid, result = runner.validate_path(data.project_path)
        if not valid:
            raise HTTPException(status_code=400, detail=result)
        data.project_path = result
    agent = store.update_agent(agent_id, data)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent.model_dump()


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete an agent and its history."""
    # Stop any running process first
    await runner.stop(agent_id)
    if not store.delete_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"ok": True}


@app.post("/api/agents/{agent_id}/reset")
def reset_agent(agent_id: str):
    """Reset an agent's conversation history."""
    if not store.reset_conversation(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"ok": True}


@app.get("/api/agents/{agent_id}/history")
def get_history(agent_id: str):
    """Get chat history for an agent."""
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return [m.model_dump() for m in store.get_history(agent_id)]


@app.post("/api/agents/{agent_id}/stop")
async def stop_agent(agent_id: str):
    """Stop a running Claude process for an agent."""
    if await runner.stop(agent_id):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="No active process")


# --- WebSocket ---

@app.websocket("/api/ws/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str):
    """WebSocket endpoint for real-time chat with an agent."""
    agent = store.get_agent(agent_id)
    if not agent:
        await websocket.close(code=4004, reason="Agent not found")
        return

    await websocket.accept()
    logger.info(f"WebSocket connected for agent {agent_id}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "content": "Invalid JSON"})
                continue

            msg_type = msg.get("type")

            if msg_type == "stop":
                await runner.stop(agent_id)
                await websocket.send_json({"type": "status", "content": "stopped"})
                continue

            if msg_type == "chat":
                content = msg.get("content", "").strip()
                if not content:
                    continue

                # Re-read agent in case project changed
                agent = store.get_agent(agent_id)
                if not agent:
                    await websocket.send_json({"type": "error", "content": "Agent not found"})
                    continue

                # Save user message
                store.add_message(agent_id, Message(role="user", content=content))

                await websocket.send_json({"type": "status", "content": "running"})

                # Stream Claude output
                full_output = ""
                async for chunk in runner.run(
                    agent_id, content, agent.project_path, agent.has_conversation
                ):
                    full_output += chunk
                    await websocket.send_json({"type": "chunk", "content": chunk})

                # Save assistant message
                if full_output:
                    store.add_message(
                        agent_id, Message(role="assistant", content=full_output)
                    )
                    store.set_has_conversation(agent_id, True)

                await websocket.send_json({"type": "done", "content": ""})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for agent {agent_id}")
        # Stop any running process when client disconnects
        await runner.stop(agent_id)


# --- Static file serving (frontend) ---

# Look for the bundled frontend dist relative to this file
_frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(_frontend_dist):
    # Serve static assets
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA - return index.html for all non-API routes."""
        file_path = os.path.join(_frontend_dist, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(_frontend_dist, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT)

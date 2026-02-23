"""JSON file persistence for agents and chat history."""

import json
import os
import uuid

from .models import Agent, AgentCreate, AgentUpdate, Message
from .config import DATA_DIR


class AgentStore:
    """Manages agent and history persistence via JSON files."""

    def __init__(self):
        self._agents_file = os.path.join(DATA_DIR, "agents.json")
        self._history_dir = os.path.join(DATA_DIR, "history")
        os.makedirs(self._history_dir, exist_ok=True)
        if not os.path.exists(self._agents_file):
            self._write_agents([])

    def _read_agents(self) -> list[Agent]:
        with open(self._agents_file) as f:
            data = json.load(f)
        return [Agent(**a) for a in data]

    def _write_agents(self, agents: list[Agent]) -> None:
        with open(self._agents_file, "w") as f:
            json.dump([a.model_dump() for a in agents], f, indent=2)

    def _history_file(self, agent_id: str) -> str:
        return os.path.join(self._history_dir, f"{agent_id}.json")

    def list_agents(self) -> list[Agent]:
        return self._read_agents()

    def get_agent(self, agent_id: str) -> Agent | None:
        for a in self._read_agents():
            if a.id == agent_id:
                return a
        return None

    def create_agent(self, data: AgentCreate) -> Agent:
        agents = self._read_agents()
        agent = Agent(id=str(uuid.uuid4()), name=data.name, project_path=data.project_path)
        agents.append(agent)
        self._write_agents(agents)
        # Initialize empty history
        self._write_history(agent.id, [])
        return agent

    def update_agent(self, agent_id: str, data: AgentUpdate) -> Agent | None:
        agents = self._read_agents()
        for i, a in enumerate(agents):
            if a.id == agent_id:
                if data.name is not None:
                    a.name = data.name
                if data.project_path is not None:
                    a.project_path = data.project_path
                agents[i] = a
                self._write_agents(agents)
                return a
        return None

    def delete_agent(self, agent_id: str) -> bool:
        agents = self._read_agents()
        new_agents = [a for a in agents if a.id != agent_id]
        if len(new_agents) == len(agents):
            return False
        self._write_agents(new_agents)
        # Remove history file
        hf = self._history_file(agent_id)
        if os.path.exists(hf):
            os.remove(hf)
        return True

    def reset_conversation(self, agent_id: str) -> bool:
        agent = self.get_agent(agent_id)
        if not agent:
            return False
        self._write_history(agent_id, [])
        # Update has_conversation flag
        agents = self._read_agents()
        for i, a in enumerate(agents):
            if a.id == agent_id:
                a.has_conversation = False
                agents[i] = a
                self._write_agents(agents)
                break
        return True

    def set_has_conversation(self, agent_id: str, value: bool) -> None:
        agents = self._read_agents()
        for i, a in enumerate(agents):
            if a.id == agent_id:
                a.has_conversation = value
                agents[i] = a
                self._write_agents(agents)
                break

    def get_history(self, agent_id: str) -> list[Message]:
        hf = self._history_file(agent_id)
        if not os.path.exists(hf):
            return []
        with open(hf) as f:
            data = json.load(f)
        return [Message(**m) for m in data]

    def add_message(self, agent_id: str, message: Message) -> None:
        history = self.get_history(agent_id)
        history.append(message)
        self._write_history(agent_id, history)

    def _write_history(self, agent_id: str, history: list[Message]) -> None:
        with open(self._history_file(agent_id), "w") as f:
            json.dump([m.model_dump() for m in history], f, indent=2)


# Global store instance
store = AgentStore()

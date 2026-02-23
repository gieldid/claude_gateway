"""Data models for the Claude Gateway dashboard."""

from datetime import datetime
from pydantic import BaseModel, Field


class Agent(BaseModel):
    id: str
    name: str
    project_path: str
    has_conversation: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class AgentCreate(BaseModel):
    name: str
    project_path: str


class AgentUpdate(BaseModel):
    name: str | None = None
    project_path: str | None = None


class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class Project(BaseModel):
    name: str
    path: str

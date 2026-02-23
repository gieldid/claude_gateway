"""Claude Code CLI wrapper for spawning and managing Claude processes."""

import asyncio
import os
import signal
import subprocess
from dataclasses import dataclass, field
from typing import AsyncGenerator


@dataclass
class ClaudeProcess:
    """Represents a running Claude Code process."""

    process: asyncio.subprocess.Process
    working_dir: str
    cancelled: bool = field(default=False)


class ClaudeRunner:
    """Manages Claude Code CLI processes."""

    def __init__(self):
        self._active_processes: dict[str, ClaudeProcess] = {}  # session_id -> process

    def is_running(self, session_id: str) -> bool:
        """Check if a Claude process is running for this session."""
        return session_id in self._active_processes

    def get_working_dir(self, session_id: str) -> str | None:
        """Get the working directory for an active process."""
        if session_id in self._active_processes:
            return self._active_processes[session_id].working_dir
        return None

    async def stop(self, session_id: str) -> bool:
        """Stop the active Claude process for a session."""
        if session_id not in self._active_processes:
            return False

        # Remove immediately so new run() calls aren't blocked while we wait
        # for the process to exit.
        proc_info = self._active_processes.pop(session_id)
        proc_info.cancelled = True

        try:
            # Send SIGTERM first
            proc_info.process.terminate()
            # Wait briefly for graceful shutdown
            try:
                await asyncio.wait_for(proc_info.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                # Force kill if needed
                proc_info.process.kill()
                await proc_info.process.wait()
        except ProcessLookupError:
            pass  # Already terminated

        return True

    def validate_path(self, path: str) -> tuple[bool, str]:
        """Validate a project path for security."""
        # Expand user and resolve path
        expanded = os.path.expanduser(path)
        resolved = os.path.realpath(expanded)

        # Check if path exists and is a directory
        if not os.path.exists(resolved):
            return False, f"Path does not exist: {resolved}"

        if not os.path.isdir(resolved):
            return False, f"Path is not a directory: {resolved}"

        # Basic security: prevent access to sensitive system directories
        sensitive_paths = ["/etc", "/root", "/var", "/usr", "/bin", "/sbin", "/boot"]
        for sensitive in sensitive_paths:
            if resolved.startswith(sensitive):
                return False, f"Access to {sensitive} is not allowed"

        return True, resolved

    async def run(
        self, session_id: str, message: str, working_dir: str, continue_conversation: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        Run Claude Code CLI and yield output chunks.

        Args:
            session_id: Session identifier (e.g. Telegram chat ID or dashboard agent ID)
            message: User message to send to Claude
            working_dir: Directory to run Claude in
            continue_conversation: If True, use --continue to resume the last conversation

        Yields:
            Output chunks from Claude
        """
        if session_id in self._active_processes:
            yield "A Claude process is already running. Use /stop to cancel it first."
            return

        # Validate working directory
        valid, result = self.validate_path(working_dir)
        if not valid:
            yield f"Invalid working directory: {result}"
            return

        working_dir = result

        # Build command - use --dangerously-skip-permissions since there is
        # no interactive terminal to approve tool use (auth is handled by
        # the Telegram chat ID whitelist and path validation)
        cmd = ["claude", "--print", "--dangerously-skip-permissions"]
        if continue_conversation:
            cmd.append("--continue")
        cmd.append(message)

        proc_info = None
        try:
            # Start process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=working_dir,
                # Prevent Claude from trying to read input
                stdin=asyncio.subprocess.DEVNULL,
            )

            proc_info = ClaudeProcess(process=process, working_dir=working_dir)
            self._active_processes[session_id] = proc_info

            # Read output
            buffer = ""
            while True:
                if proc_info.cancelled:
                    yield "\n\n_Operation cancelled._"
                    break

                try:
                    # Read with timeout to allow checking cancelled flag
                    chunk = await asyncio.wait_for(
                        process.stdout.read(1024), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    continue

                if not chunk:
                    # Process ended
                    if buffer:
                        yield buffer
                    break

                text = chunk.decode("utf-8", errors="replace")
                buffer += text

                # Yield complete lines when we have enough content
                if len(buffer) >= 500 or "\n" in buffer:
                    yield buffer
                    buffer = ""

            # Wait for process to complete
            await process.wait()

        except FileNotFoundError:
            yield "Error: `claude` command not found. Make sure Claude Code CLI is installed and in PATH."
        except Exception as e:
            yield f"Error running Claude: {e}"
        finally:
            # Only remove our own entry - a concurrent run() may have already
            # registered a new process for the same session_id.
            if proc_info is not None and self._active_processes.get(session_id) is proc_info:
                self._active_processes.pop(session_id)


# Global runner instance
runner = ClaudeRunner()

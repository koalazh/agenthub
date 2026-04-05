"""AgentHub Backend - Custom backend for AgentHub with git command restrictions."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    SandboxBackendProtocol,
    WriteResult,
)

from agenthub.core.config import (
    ALLOWED_GIT_SUBCOMMANDS,
    DANGEROUS_PATTERNS,
    get_config,
)


class AgentHubBackend(SandboxBackendProtocol):
    """Custom backend for AgentHub with git command restrictions.

    This backend:
    - Wraps FilesystemBackend for file operations
    - Implements execute() with git command whitelist validation
    - Enforces path constraints within agenthub directory
    - Provides sandboxed git access for agent operations

    Implements SandboxBackendProtocol so isinstance checks pass correctly
    with deepagents' filesystem middleware.
    """

    def __init__(
        self,
        agenthub_dir: Path | None = None,
        agent_id: str | None = None,
        root_dir: str | Path | None = None,
        virtual_mode: bool = True,
        max_file_size_mb: int = 10,
    ) -> None:
        """Initialize the AgentHubBackend.

        Args:
            agenthub_dir: Root directory for all agents (default: ~/.agenthub)
            agent_id: Specific agent ID to restrict operations to
            root_dir: Root directory for file operations (defaults to agenthub_dir/agent_id)
            virtual_mode: Enable virtual path mode (default: True for security)
            max_file_size_mb: Maximum file size for operations
        """
        config = get_config()
        self.agenthub_dir = Path(agenthub_dir or config.agenthub_dir)
        self.agent_id = agent_id or ""

        # Set root_dir to agent-specific directory if using virtual_mode
        if root_dir is None and agent_id:
            root_dir = self.agenthub_dir / agent_id

        # Create the underlying filesystem backend for file operations
        self._fs_backend = FilesystemBackend(
            root_dir=str(root_dir) if root_dir else str(self.agenthub_dir),
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    @property
    def cwd(self) -> Path:
        """Return current working directory (from underlying backend)."""
        return self._fs_backend.cwd

    @property
    def virtual_mode(self) -> bool:
        """Return virtual mode setting."""
        return self._fs_backend.virtual_mode

    @property
    def id(self) -> str:
        """Return unique identifier for this backend instance."""
        return f"agenthub-{self.agent_id}" if self.agent_id else "agenthub-unknown"

    def _resolve_path(self, key: str) -> Path:
        """Resolve a file path with security checks.

        Delegates to underlying filesystem backend.
        """
        return self._fs_backend._resolve_path(key)

    def ls(self, path: str) -> LsResult:
        """List files in directory."""
        return self._fs_backend.ls(path)

    async def als(self, path: str) -> LsResult:
        """Async list files in directory."""
        return await asyncio.to_thread(self._fs_backend.ls, path)

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> ReadResult:
        """Read file content."""
        return self._fs_backend.read(file_path, offset=offset, limit=limit)

    async def aread(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> ReadResult:
        """Async read file content."""
        return await asyncio.to_thread(self._fs_backend.read, file_path, offset=offset, limit=limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        """Write content to a new file."""
        return self._fs_backend.write(file_path, content)

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        """Async write content to a new file."""
        return await asyncio.to_thread(self._fs_backend.write, file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit file by replacing string occurrences."""
        return self._fs_backend.edit(file_path, old_string, new_string, replace_all=replace_all)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Async edit file by replacing string occurrences."""
        return await asyncio.to_thread(
            self._fs_backend.edit, file_path, old_string, new_string, replace_all=replace_all
        )

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        """Search for literal text pattern in files."""
        return self._fs_backend.grep(pattern, path=path, glob=glob)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        """Async search for literal text pattern in files."""
        return await asyncio.to_thread(self._fs_backend.grep, pattern, path=path, glob=glob)

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        """Find files matching glob pattern."""
        return self._fs_backend.glob(pattern, path=path)

    async def aglob(self, pattern: str, path: str = "/") -> GlobResult:
        """Async find files matching glob pattern."""
        return await asyncio.to_thread(self._fs_backend.glob, pattern, path=path)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files."""
        return self._fs_backend.upload_files(files)

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Async upload multiple files."""
        return await asyncio.to_thread(self._fs_backend.upload_files, files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files."""
        return self._fs_backend.download_files(paths)

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Async download multiple files."""
        return await asyncio.to_thread(self._fs_backend.download_files, paths)

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Execute a command with git whitelist validation.

        Only allows git subcommands from the whitelist.

        Args:
            command: Shell command to execute
            timeout: Maximum execution time in seconds

        Returns:
            ExecuteResponse with output and exit code
        """
        # Validate git command
        validation_result = self._validate_git_command(command)
        if validation_result is not None:
            return validation_result

        # Execute the command
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=timeout or 30,
            )
            return ExecuteResponse(
                output=result.stdout + result.stderr,
                exit_code=result.returncode,
                truncated=False,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=self._format_error(
                    error_type="command_timeout",
                    root_cause=f"Command did not complete within {timeout or 30} seconds",
                    hint="The command took too long to execute",
                    safe_retry="Check if the repository is in a busy state, then retry with a longer timeout",
                    stop_condition="If the command consistently times out, abort and report the issue",
                ),
                exit_code=124,
                truncated=False,
            )
        except Exception as e:
            return ExecuteResponse(
                output=self._format_error(
                    error_type="execution_error",
                    root_cause=f"Unexpected error: {str(e)}",
                    hint="An unexpected error occurred during execution",
                    safe_retry="Verify the repository state with 'git status', then retry",
                    stop_condition="If the error persists, abort and report the issue",
                ),
                exit_code=1,
                truncated=False,
            )

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,  # noqa: ASYNC109
    ) -> ExecuteResponse:
        """Async execute a command with git whitelist validation."""
        return await asyncio.to_thread(self.execute, command, timeout=timeout)

    def _format_error(
        self,
        error_type: str,
        root_cause: str,
        hint: str,
        safe_retry: str,
        stop_condition: str,
    ) -> str:
        """Format a structured error message following Error Recovery Contract."""
        return "\n".join([
            f"[ERROR] {error_type}",
            f"[ROOT_CAUSE] {root_cause}",
            f"[HINT] {hint}",
            f"[SAFE_RETRY] {safe_retry}",
            f"[STOP_CONDITION] {stop_condition}",
        ])

    def _validate_git_command(self, command: str) -> ExecuteResponse | None:
        """Validate that a command is an allowed git command.

        Args:
            command: Command to validate

        Returns:
            ExecuteResponse with error if invalid, None if valid
        """
        parts = command.strip().split()
        if not parts:
            return ExecuteResponse(
                output=self._format_error(
                    error_type="empty_command",
                    root_cause="Command string is empty",
                    hint="Provide a valid git command",
                    safe_retry="Use 'git status' to verify repository state",
                    stop_condition="N/A - empty command should be caught before this",
                ),
                exit_code=1,
                truncated=False,
            )

        # Check if it's a git command
        if parts[0] != "git":
            return ExecuteResponse(
                output=self._format_error(
                    error_type="not_git_command",
                    root_cause=f"Command '{parts[0]}' is not 'git'",
                    hint="AgentHub only allows git commands for safety",
                    safe_retry="Prefix your command with 'git ' (e.g., 'git status')",
                    stop_condition="If you need to run non-git commands, abort this operation",
                ),
                exit_code=1,
                truncated=False,
            )

        if len(parts) < 2:
            return ExecuteResponse(
                output=self._format_error(
                    error_type="incomplete_git_command",
                    root_cause="Git command provided without subcommand",
                    hint="Provide a valid git subcommand",
                    safe_retry="Use 'git status' as a safe starting command",
                    stop_condition="N/A - this is a input validation issue",
                ),
                exit_code=1,
                truncated=False,
            )

        # Extract subcommand (handle git-XYZ aliases like git-status)
        subcommand = parts[1].rstrip("0123456789-")

        # Check against whitelist
        if subcommand not in ALLOWED_GIT_SUBCOMMANDS:
            return ExecuteResponse(
                output=self._format_error(
                    error_type="git_subcommand_not_allowed",
                    root_cause=f"git subcommand '{subcommand}' is not in the allowed whitelist",
                    hint=f"Only these subcommands are allowed: {', '.join(sorted(ALLOWED_GIT_SUBCOMMANDS))}",
                    safe_retry="Use 'git status' to check repository state first, then use an allowed subcommand",
                    stop_condition="If your required operation needs a disallowed subcommand, abort and report the limitation",
                ),
                exit_code=1,
                truncated=False,
            )

        # Check for dangerous patterns in the full command
        full_command = " ".join(parts[1:])
        for pattern in DANGEROUS_PATTERNS:
            if pattern in full_command:
                return ExecuteResponse(
                    output=self._format_error(
                        error_type="dangerous_pattern_detected",
                        root_cause=f"Dangerous pattern '{pattern}' found in command",
                        hint="This pattern could cause data loss or security issues",
                        safe_retry="Remove the dangerous element and retry, or abort if essential",
                        stop_condition="If the dangerous pattern is required for the task, abort",
                    ),
                    exit_code=1,
                    truncated=False,
                )

        return None


def create_agent_backend(
    agent_id: str,
    agenthub_dir: Path | None = None,
    virtual_mode: bool = False,
    root_dir: Path | None = None,
) -> AgentHubBackend:
    """Factory function to create an AgentHubBackend for a specific agent.

    Args:
        agent_id: The agent's unique identifier
        agenthub_dir: Optional custom agenthub directory
        virtual_mode: If True, restrict file access to within agent directory.
                      If False, allow access to sibling directories (for skill execution).
        root_dir: Optional override for root directory. If not provided,
                  defaults to agenthub_dir/agent_id.

    Returns:
        Configured AgentHubBackend instance
    """
    config = get_config()
    base_dir = Path(agenthub_dir or config.agenthub_dir)
    agent_dir = base_dir / agent_id

    # Ensure agent directory exists
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Use provided root_dir or default to agent-specific directory
    effective_root_dir = root_dir if root_dir is not None else agent_dir

    return AgentHubBackend(
        agenthub_dir=base_dir,
        agent_id=agent_id,
        root_dir=effective_root_dir,
        virtual_mode=virtual_mode,
    )

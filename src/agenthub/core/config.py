"""Configuration for AgentHub."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


# Default paths
DEFAULT_AGENTHUB_DIR = Path.home() / ".agenthub"
DEFAULT_BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "builtin_skills"

# Default timeouts (in seconds)
DEFAULT_TIMEOUT = 120
EVOLUTION_TIMEOUT = 180
SELF_EVOLUTION_TIMEOUT = 300
INIT_AGENT_TIMEOUT = 120

# Git whitelist for execute command
ALLOWED_GIT_SUBCOMMANDS: set[str] = {
    # 安全命令
    "status",     # 查看状态
    "add",        # 仅限 git add <specific_file>
    "commit",     # 创建演进记录
    "log",        # 读取历史
    "diff",       # 比较差异
    "show",       # 查看 commit
    "ls-files",   # 列出文件
    "reset",      # 仅限 --hard（rollback）
    "rev-parse",  # 验证 commit hash
}

# 禁止的命令（安全风险）
FORBIDDEN_GIT_SUBCOMMANDS: set[str] = {
    "push",       # 禁止推送到远程
    "pull",       # 禁止从远程拉取
    "fetch",      # 禁止从远程获取
    "branch",     # 禁止分支操作
    "checkout",   # 禁止切换分支
    "merge",      # 禁止合并
    "rebase",     # 禁止变基
    "clone",      # 禁止克隆
    "init",       # 禁止初始化
    "stash",      # 禁止储藏
    "tag",        # 禁止标签
    "describe",   # 禁止描述
    "symbolic-ref",  # 禁止符号引用
}

# Dangerous patterns that should be blocked
DANGEROUS_PATTERNS = [
    "--force",
    "-f",
    "--no-verify",
    ";",
    "&&",
    "||",
    "|",
    "`",
    "$",
    "\n",
]


def get_agenthub_dir() -> Path:
    """Get the agenthub directory path."""
    return Path(os.environ.get("AGENTHUB_DIR", DEFAULT_AGENTHUB_DIR))


def get_builtin_skills_dir() -> Path:
    """Get the built-in skills directory path."""
    return Path(os.environ.get("BUILTIN_SKILLS_DIR", DEFAULT_BUILTIN_SKILLS_DIR))


def get_default_model() -> str:
    """Get the default model from MODEL_NAME environment variable.

    Returns:
        Model string in "provider:model-name" format, or fallback default.
    """
    return os.environ.get("MODEL_NAME", "anthropic:claude-sonnet-4-6")


def resolve_model(model: str | "BaseChatModel") -> "BaseChatModel":
    """Resolve a model string or instance to a BaseChatModel.

    Uses deepagents' resolve_model for consistent model resolution.

    Args:
        model: Either a string like "anthropic:claude-sonnet-4-6" or a BaseChatModel instance.

    Returns:
        A BaseChatModel instance.
    """
    from deepagents._models import resolve_model as deepagents_resolve_model
    return deepagents_resolve_model(model)


class AgentHubConfig:
    """Configuration for AgentHub runtime."""

    def __init__(
        self,
        agenthub_dir: Path | None = None,
        builtin_skills_dir: Path | None = None,
        default_timeout: int = DEFAULT_TIMEOUT,
        evolution_timeout: int = EVOLUTION_TIMEOUT,
        self_evolution_timeout: int = SELF_EVOLUTION_TIMEOUT,
        init_agent_timeout: int = INIT_AGENT_TIMEOUT,
        pokemon_salt: str = "pokemon-friend-2026-401",
    ) -> None:
        self.agenthub_dir = agenthub_dir or get_agenthub_dir()
        self.builtin_skills_dir = builtin_skills_dir or get_builtin_skills_dir()
        self.default_timeout = default_timeout
        self.evolution_timeout = evolution_timeout
        self.self_evolution_timeout = self_evolution_timeout
        self.init_agent_timeout = init_agent_timeout
        self.pokemon_salt = pokemon_salt

    def ensure_dirs(self) -> None:
        """Ensure required directories exist."""
        self.agenthub_dir.mkdir(parents=True, exist_ok=True)


# Global config instance
_config: AgentHubConfig | None = None


def get_config() -> AgentHubConfig:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = AgentHubConfig()
    return _config


def set_config(config: AgentHubConfig) -> None:
    """Set the global config instance."""
    global _config
    _config = config

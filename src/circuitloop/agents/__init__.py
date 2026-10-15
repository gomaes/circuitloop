"""Agent backends: claude, opencode, mock."""

from __future__ import annotations

import os

from ..config import AgentConfig
from .base import AgentBackend, AgentError, AgentResult, AgentTask
from .claude import ClaudeBackend
from .mock import MockBackend
from .opencode import OpenCodeBackend

__all__ = ["AgentBackend", "AgentError", "AgentResult", "AgentTask", "make_backend"]


def make_backend(cfg: AgentConfig) -> AgentBackend:
    kw = {"model": cfg.model, "extra_args": cfg.extra_args, "max_budget_usd": cfg.max_budget_usd}
    if cfg.backend == "claude":
        return ClaudeBackend(**kw)
    if cfg.backend == "opencode":
        return OpenCodeBackend(**kw)
    if cfg.backend == "mock":
        d = os.environ.get("CLOOP_MOCK_DIR")
        if not d:
            raise AgentError("agent 'mock' needs CLOOP_MOCK_DIR=<script dir>")
        return MockBackend(d, **kw)
    raise AgentError(f"unknown agent backend {cfg.backend!r}")

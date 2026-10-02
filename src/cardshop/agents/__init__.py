"""The LLM layer: escalation for what deterministic code cannot decide."""
from .tools import build_smolagent_tools, build_tool_functions
from .triage import AgentTriage, TriageOutcome, build_agent

__all__ = [
    "build_tool_functions", "build_smolagent_tools",
    "AgentTriage", "TriageOutcome", "build_agent",
]

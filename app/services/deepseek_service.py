"""Backward compatibility alias for AgentService."""
from app.services.agent_service import AgentService, TokenAndReasoningCallbackHandler

# Alias DeepSeekService to AgentService for existing dependencies
DeepSeekService = AgentService

__all__ = ["AgentService", "DeepSeekService", "TokenAndReasoningCallbackHandler"]

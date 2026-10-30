"""Exception hierarchy. Every JARVIS-raised error derives from JarvisError."""
from __future__ import annotations


class JarvisError(Exception):
    """Base class for all JARVIS errors."""


class ConfigError(JarvisError):
    """Invalid or unreadable configuration."""


class LLMError(JarvisError):
    """Failure while talking to an LLM provider."""


class ProviderNotFoundError(LLMError):
    """Requested LLM provider is not registered."""


class PlanningError(JarvisError):
    """Planner could not produce a valid plan."""


class TaskError(JarvisError):
    """Invalid task operation (unknown id, illegal status transition...)."""


class ToolError(JarvisError):
    """Tool lookup or registration problem."""


class SecurityError(JarvisError):
    """Base class for permission/security problems."""


class PermissionDeniedError(SecurityError):
    """Action blocked by the permission system."""


class InvalidRequestError(SecurityError):
    """Malformed permission request or resource (always treated as a denial)."""


class PolicyError(SecurityError):
    """Invalid or unreadable security policy/configuration (JARVIS refuses to start with it)."""


class VoiceError(JarvisError):
    """Base class for voice-interface problems."""


class VoiceUnavailableError(VoiceError):
    """Audio hardware, backend library or system tool is missing."""


class STTError(VoiceError):
    """Speech-to-text failure."""


class TTSError(VoiceError):
    """Text-to-speech failure."""


class EndOfInput(VoiceError):
    """The audio/text source is exhausted; the voice session ends cleanly."""


class MemoryStoreError(JarvisError):
    """Base class for memory problems (named to avoid shadowing the builtin MemoryError)."""


class MemoryValidationError(MemoryStoreError):
    """Invalid memory content, metadata or query."""


class SecretRejectedError(MemoryValidationError):
    """Content looks like a secret (API key, password, token...) and is never stored."""


class MemoryNotFoundError(MemoryStoreError):
    """No memory entry with the given id."""


class MemoryDisabledError(MemoryStoreError):
    """Memory is disabled in the configuration."""


class MemoryLimitError(MemoryStoreError):
    """A configured memory limit (e.g. max_entries) was reached."""


class HistoryError(JarvisError):
    """The persistent history of finished work could not be read or written (or was given invalid input)."""


class ComputerControlError(JarvisError):
    """Base class for computer-control problems (see jarvis.computer.errors for the structured subclass)."""

"""AURA Intelligence Engine (Phase 2).

Public API:
  - InferenceEngine: top-level coordinator (providers, resources, modes).
  - HardwareProfile / detect_hardware: hardware detection.
  - AIMode / ModeManager: local/hybrid/offline modes.
  - ModelManager / ModelInfo: model discovery and (user-initiated) downloads.
  - ResourceManager: adaptive resource policy.
  - ConversationManager: conversation history and context-window management.
  - HealthMonitor: provider health polling.
"""
from .hardware import HardwareProfile, detect_hardware
from .inference import InferenceEngine, InferenceError
from .mode_manager import AIMode, ModeManager
from .model_info import ModelInfo, ModelFormat
from .model_manager import ModelManager
from .provider import InferenceRequest, InferenceResult, Provider, ProviderState
from .resource_manager import ResourceManager
from .conversation import Conversation, ConversationManager
from .health import HealthMonitor

__all__ = [
    "InferenceEngine", "InferenceError",
    "HardwareProfile", "detect_hardware",
    "AIMode", "ModeManager",
    "ModelInfo", "ModelFormat", "ModelManager",
    "InferenceRequest", "InferenceResult", "Provider", "ProviderState",
    "ResourceManager",
    "Conversation", "ConversationManager",
    "HealthMonitor",
]

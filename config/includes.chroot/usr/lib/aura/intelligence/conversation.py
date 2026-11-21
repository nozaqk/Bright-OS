"""Conversation manager — maintains per-conversation history and manages
context-window truncation.

Designed to be lightweight: history is held in memory and optionally
persisted to the AURA state dir. No cloud sync.
"""
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("aura.intelligence.conversation")

AURA_STATE_DIR = "/var/lib/aura"
CONVERSATION_DIR = os.path.join(AURA_STATE_DIR, "conversations")


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    tokens: int = 0  # approximate token count (chars/4)


@dataclass
class Conversation:
    id: str
    system_prompt: str = ""
    messages: List[Message] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add_user(self, text: str) -> Message:
        msg = Message("user", text)
        msg.tokens = _estimate_tokens(text)
        self.messages.append(msg)
        self.updated_at = time.time()
        return msg

    def add_assistant(self, text: str) -> Message:
        msg = Message("assistant", text)
        msg.tokens = _estimate_tokens(text)
        self.messages.append(msg)
        self.updated_at = time.time()
        return msg

    def total_tokens(self) -> int:
        total = _estimate_tokens(self.system_prompt)
        for m in self.messages:
            total += m.tokens
        return total

    def format_prompt(self, max_tokens: int) -> str:
        """Produce a prompt string from history that fits within max_tokens.

        We keep the system prompt and the most recent messages, dropping
        older turns until the estimated total fits.
        """
        budget = max_tokens - 256  # leave room for generation
        parts: List[str] = []
        sys_tok = _estimate_tokens(self.system_prompt)
        used = sys_tok
        if self.system_prompt:
            parts.append(self.system_prompt)
        # Walk messages in reverse, keeping as many recent as fit
        kept: List[str] = []
        for m in reversed(self.messages):
            if used + m.tokens > budget and kept:
                break
            if m.role == "user":
                kept.append(f"User: {m.content}")
            elif m.role == "assistant":
                kept.append(f"Assistant: {m.content}")
            else:
                kept.append(m.content)
            used += m.tokens
        parts.extend(reversed(kept))
        parts.append("Assistant:")
        return "\n\n".join(parts)


def _estimate_tokens(text: str) -> int:
    """Very rough token estimate: ~4 chars per token for English."""
    if not text:
        return 0
    return max(1, len(text) // 4)


class ConversationManager:
    def __init__(self, state_dir: str = CONVERSATION_DIR, persist: bool = False):
        self._convs: Dict[str, Conversation] = {}
        self._lock = threading.Lock()
        self._state_dir = state_dir
        self._persist = persist
        if persist:
            try:
                os.makedirs(state_dir, exist_ok=True)
            except OSError as e:
                logger.warning("Could not create conversation dir %s: %s",
                               state_dir, e)

    def new_conversation(self, system_prompt: str = "",
                         conv_id: Optional[str] = None) -> Conversation:
        cid = conv_id or str(uuid.uuid4())
        conv = Conversation(id=cid, system_prompt=system_prompt)
        with self._lock:
            self._convs[cid] = conv
        return conv

    def get(self, conv_id: str) -> Optional[Conversation]:
        with self._lock:
            return self._convs.get(conv_id)

    def delete(self, conv_id: str) -> bool:
        with self._lock:
            return self._convs.pop(conv_id, None) is not None

    def list_ids(self) -> List[str]:
        with self._lock:
            return list(self._convs.keys())

    def append_user(self, conv_id: str, text: str) -> Optional[Message]:
        conv = self.get(conv_id)
        if not conv:
            return None
        msg = conv.add_user(text)
        self._maybe_save(conv)
        return msg

    def append_assistant(self, conv_id: str, text: str) -> Optional[Message]:
        conv = self.get(conv_id)
        if not conv:
            return None
        msg = conv.add_assistant(text)
        self._maybe_save(conv)
        return msg

    def _maybe_save(self, conv: Conversation):
        if not self._persist:
            return
        try:
            path = os.path.join(self._state_dir, f"{conv.id}.json")
            data = {
                "id": conv.id,
                "system_prompt": conv.system_prompt,
                "created_at": conv.created_at,
                "updated_at": conv.updated_at,
                "messages": [
                    {"role": m.role, "content": m.content,
                     "timestamp": m.timestamp, "tokens": m.tokens}
                    for m in conv.messages
                ],
            }
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except OSError as e:
            logger.warning("Failed to persist conversation %s: %s", conv.id, e)

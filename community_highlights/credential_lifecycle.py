"""Serialize credential writes with provider disconnect operations.

The backend is one supervised asyncio process. Locks and disconnect state are
scoped to its event loop so tests using separate asyncio.run() loops cannot
reuse a lock bound to an earlier loop.
"""
from __future__ import annotations

import asyncio
import threading
import weakref
from contextlib import asynccontextmanager
from typing import AsyncIterator


class _LoopState:
    def __init__(self) -> None:
        self.locks = {
            "twitch": asyncio.Lock(),
            "youtube": asyncio.Lock(),
        }
        self.disconnecting: set[str] = set()
        self.generation = {"twitch": 0, "youtube": 0}


_registry_lock = threading.RLock()
_loop_states: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopState] = (
    weakref.WeakKeyDictionary()
)


def _state() -> _LoopState:
    loop = asyncio.get_running_loop()
    with _registry_lock:
        state = _loop_states.get(loop)
        if state is None:
            state = _LoopState()
            _loop_states[loop] = state
        return state


@asynccontextmanager
async def provider_credential_lock(provider: str) -> AsyncIterator[None]:
    """Serialize refresh/auth credential writes with disconnect for one provider."""
    state = _state()
    lock = state.locks.get(provider)
    if lock is None:
        raise ValueError("Unsupported Community Highlights provider.")
    async with lock:
        yield


@asynccontextmanager
async def provider_disconnect_lock(provider: str) -> AsyncIterator[None]:
    """Own the credential boundary while revoking and deleting a provider grant."""
    state = _state()
    lock = state.locks.get(provider)
    if lock is None:
        raise ValueError("Unsupported Community Highlights provider.")
    async with lock:
        state.generation[provider] += 1
        state.disconnecting.add(provider)
        try:
            yield
        finally:
            state.disconnecting.discard(provider)


def provider_is_disconnecting(provider: str) -> bool:
    """Return whether the current event loop is inside provider disconnect."""
    return provider in _state().disconnecting


def provider_operation_generation(provider: str) -> int:
    """Return the disconnect generation for optimistic admission of OAuth starts.

    A start that began before a disconnect may finish its provider HTTP setup
    afterward. Comparing its captured generation prevents it from registering
    a fresh pending flow after Disconnect has already cancelled all flows.
    """
    state = _state()
    if provider not in state.generation:
        raise ValueError("Unsupported Community Highlights provider.")
    return state.generation[provider]

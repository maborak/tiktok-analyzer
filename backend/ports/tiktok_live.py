"""Port for the TikTok WebCast listener (the "outside world" — i.e.,
the tiktok-live library wrapper). The service depends on this; the
TikTokLive-specific adapter implements it."""

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Protocol


class TikTokLiveEventCallback(Protocol):
    """A coroutine called once per event. Implementations are async so
    they can do DB I/O + WS broadcast without blocking the listener."""

    async def __call__(self, *, type: str, payload: dict, room_id: int | None) -> None:
        ...


class TikTokLiveSessionPort(ABC):
    """One live-stream listener. Wraps a TikTokLive client.

    Lifecycle: start() → events flow via the callback → stop() to tear down.
    Auto-reconnect logic lives in the adapter, not here.
    """

    @property
    @abstractmethod
    def unique_id(self) -> str: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @property
    @abstractmethod
    def room_id(self) -> int | None: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...


class TikTokLiveSessionFactoryPort(ABC):
    """Factory the service uses to spin up new listener sessions."""

    @abstractmethod
    def create(
        self,
        unique_id: str,
        on_event: Callable[..., Awaitable[None]],
        on_state_change: Callable[[str], Awaitable[None]] | None = None,
        on_terminal_error: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> TikTokLiveSessionPort: ...

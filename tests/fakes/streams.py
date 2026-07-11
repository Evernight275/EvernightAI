from collections.abc import AsyncIterator
from typing import Generic, TypeVar


EventType = TypeVar("EventType")


class EventStream(Generic[EventType]):
    def __init__(self, events: list[EventType]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[EventType]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[EventType]:
        for event in self._events:
            yield event


class EmptyStream(Generic[EventType]):
    def __aiter__(self) -> AsyncIterator[EventType]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[EventType]:
        if False:
            yield

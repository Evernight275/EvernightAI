import asyncio
import codecs

from EvernightAI.core.schema.sandbox import SandboxOutputEvent, SandboxOutputStream


class BoundedSandboxOutput:
    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars
        self.stdout = ""
        self.stderr = ""
        self.events: list[SandboxOutputEvent] = []
        self.truncated = False
        self._event_chars = 0

    async def collect(
        self, reader: asyncio.StreamReader | None, stream: SandboxOutputStream
    ) -> None:
        if reader is None:
            return
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while chunk := await reader.read(4096):
            self._append(stream, decoder.decode(chunk))
        self._append(stream, decoder.decode(b"", final=True))

    def _append(self, stream: SandboxOutputStream, text: str) -> None:
        if not text:
            return
        current = getattr(self, stream.value)
        remaining = self.max_chars - len(current)
        setattr(self, stream.value, current + text[:remaining])
        truncated = len(text) > remaining
        self.truncated = self.truncated or truncated
        event_remaining = self.max_chars - self._event_chars
        if event_remaining > 0:
            visible = text[:event_remaining]
            self.events.append(
                SandboxOutputEvent(
                    stream=stream,
                    text=visible,
                    truncated=truncated or len(text) > event_remaining,
                )
            )
            self._event_chars += len(visible)

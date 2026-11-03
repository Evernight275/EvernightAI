import pytest
from pydantic import ValidationError

from EvernightAI.core.schema.log import Log, LogLevel
from EvernightAI.core.schema.trace import TraceEvent


def test_observability_sequences_are_positive_when_present() -> None:
    with pytest.raises(ValidationError):
        TraceEvent(sequence=0, event_type="invalid")

    with pytest.raises(ValidationError):
        Log(sequence=0, level=LogLevel.INFO, source="test", message="invalid")

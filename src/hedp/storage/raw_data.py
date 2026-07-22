from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class RawData:
    source: str
    timestamp: datetime
    payload: dict[str, object]
    target_date: date | None = None
    metadata: dict[str, object] | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "source": self.source,
                "timestamp": self.timestamp.isoformat(),
                "payload": self.payload,
                "target_date": (
                    self.target_date.isoformat()
                    if self.target_date is not None
                    else None
                ),
                "metadata": self.metadata,
            }
        )

    @classmethod
    def from_json(cls, value: str) -> "RawData":
        data = json.loads(value)
        target_date = data.get("target_date")
        return cls(
            source=data["source"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            payload=data["payload"],
            target_date=(
                date.fromisoformat(target_date)
                if target_date is not None
                else None
            ),
            metadata=data.get("metadata"),
        )

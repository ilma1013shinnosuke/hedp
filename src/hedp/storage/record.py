from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Record:
    source: str
    timestamp: datetime
    metric: str
    value: int | float | None
    unit: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "source": self.source,
                "timestamp": self.timestamp.isoformat(),
                "metric": self.metric,
                "value": self.value,
                "unit": self.unit,
            }
        )

    @classmethod
    def from_json(cls, value: str) -> "Record":
        data = json.loads(value)
        return cls(
            source=data["source"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metric=data["metric"],
            value=data["value"],
            unit=data["unit"],
        )

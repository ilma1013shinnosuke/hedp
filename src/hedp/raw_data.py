import json
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RawData:
    source: str
    timestamp: datetime
    payload: dict[str, object]

    def to_json(self) -> str:
        return json.dumps(
            {
                "source": self.source,
                "timestamp": self.timestamp.isoformat(),
                "payload": self.payload,
            }
        )

    @classmethod
    def from_json(cls, value: str) -> "RawData":
        data = json.loads(value)
        return cls(
            source=data["source"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            payload=data["payload"],
        )

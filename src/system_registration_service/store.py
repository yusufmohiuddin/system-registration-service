from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class RegisteredSystem:
    id: str
    hostname: str
    platform: str
    installed_version: str
    registered_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SystemStore:
    """Thread-safe in-memory store for the bounded demonstration service."""

    def __init__(self) -> None:
        self._systems: dict[str, RegisteredSystem] = {}
        self._lock = Lock()

    def register(self, hostname: str, platform: str, installed_version: str) -> RegisteredSystem:
        system = RegisteredSystem(
            id=str(uuid4()),
            hostname=hostname,
            platform=platform,
            installed_version=installed_version,
            registered_at=datetime.now(UTC).isoformat(),
        )
        with self._lock:
            self._systems[system.id] = system
        return system

    def get(self, system_id: str) -> RegisteredSystem | None:
        with self._lock:
            return self._systems.get(system_id)

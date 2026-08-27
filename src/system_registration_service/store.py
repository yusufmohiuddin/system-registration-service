from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class RegisteredSystem:
    id: str
    hostname: str
    platform: str
    installed_version: str
    registered_at: str
    last_check_in: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


PatchState = Literal["queued", "completed", "failed"]


@dataclass(frozen=True, slots=True)
class PatchRequest:
    id: str
    system_id: str
    target_version: str
    state: PatchState
    requested_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SystemStore:
    """Thread-safe in-memory store for the bounded demonstration service."""

    def __init__(self) -> None:
        self._systems: dict[str, RegisteredSystem] = {}
        self._patch_requests: dict[str, PatchRequest] = {}
        self._lock = Lock()

    def register(self, hostname: str, platform: str, installed_version: str) -> RegisteredSystem:
        now = datetime.now(UTC).isoformat()
        system = RegisteredSystem(
            id=str(uuid4()),
            hostname=hostname,
            platform=platform,
            installed_version=installed_version,
            registered_at=now,
            last_check_in=now,
        )
        with self._lock:
            self._systems[system.id] = system
        return system

    def get(self, system_id: str) -> RegisteredSystem | None:
        with self._lock:
            return self._systems.get(system_id)

    def list_systems(self) -> list[RegisteredSystem]:
        with self._lock:
            return sorted(self._systems.values(), key=lambda system: system.hostname)

    def check_in(self, system_id: str, installed_version: str) -> RegisteredSystem | None:
        with self._lock:
            current = self._systems.get(system_id)
            if current is None:
                return None
            updated = replace(
                current,
                installed_version=installed_version,
                last_check_in=datetime.now(UTC).isoformat(),
            )
            self._systems[system_id] = updated
            return updated

    def request_patch(self, system_id: str, target_version: str) -> PatchRequest | None:
        with self._lock:
            if system_id not in self._systems:
                return None
            patch_request = PatchRequest(
                id=str(uuid4()),
                system_id=system_id,
                target_version=target_version,
                state="queued",
                requested_at=datetime.now(UTC).isoformat(),
            )
            self._patch_requests[patch_request.id] = patch_request
            return patch_request

    def list_patch_requests(self) -> list[PatchRequest]:
        with self._lock:
            return sorted(
                self._patch_requests.values(),
                key=lambda patch_request: patch_request.requested_at,
                reverse=True,
            )

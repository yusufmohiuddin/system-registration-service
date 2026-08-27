import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Flask, Response, jsonify, render_template, request
from packaging.version import InvalidVersion, Version
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from system_registration_service.store import RegisteredSystem, SystemStore

REQUESTS = Counter(
    "system_registration_http_requests_total",
    "HTTP requests processed by the service.",
    ["method", "endpoint", "status"],
)
LATENCY = Histogram(
    "system_registration_http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "endpoint"],
)
INVENTORY = Gauge(
    "system_registration_inventory",
    "Current systems grouped by compliance status.",
    ["status"],
)
PATCH_REQUESTS = Counter(
    "system_registration_patch_requests_total",
    "Patch requests accepted by the service.",
)


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _validated_version(value: str, field: str) -> Version:
    try:
        return Version(value)
    except InvalidVersion as error:
        raise ValueError(f"{field} must be a valid software version") from error


def _system_status(system: RegisteredSystem, target: Version, stale_after: timedelta) -> str:
    last_check_in = datetime.fromisoformat(system.last_check_in)
    if datetime.now(UTC) - last_check_in > stale_after:
        return "stale"
    if Version(system.installed_version) < target:
        return "patch_required"
    return "compliant"


def create_app(store: SystemStore | None = None) -> Flask:
    app = Flask(__name__)
    app.config["STORE"] = store or SystemStore()
    app.config["SERVICE_VERSION"] = os.getenv("SERVICE_VERSION", "0.2.0")
    app.config["GIT_SHA"] = os.getenv("GIT_SHA", "local")
    app.config["ENVIRONMENT"] = os.getenv("ENVIRONMENT", "development")
    app.config["TARGET_VERSION"] = os.getenv("TARGET_VERSION", "1.3.0")
    app.config["STALE_AFTER_MINUTES"] = int(os.getenv("STALE_AFTER_MINUTES", "60"))

    def service_store() -> SystemStore:
        configured_store: SystemStore = app.config["STORE"]
        return configured_store

    def target_version() -> Version:
        return _validated_version(app.config["TARGET_VERSION"], "TARGET_VERSION")

    def inventory() -> list[dict[str, Any]]:
        target = target_version()
        stale_after = timedelta(minutes=app.config["STALE_AFTER_MINUTES"])
        systems: list[dict[str, Any]] = []
        counts = {"compliant": 0, "patch_required": 0, "stale": 0}
        for system in service_store().list_systems():
            status = _system_status(system, target, stale_after)
            counts[status] += 1
            systems.append({**system.as_dict(), "status": status})
        for status, count in counts.items():
            INVENTORY.labels(status).set(count)
        return systems

    @app.before_request
    def start_timer() -> None:
        request.start_time = time.perf_counter()  # type: ignore[attr-defined]

    @app.after_request
    def record_request(response: Response) -> Response:
        endpoint = request.endpoint or "unknown"
        REQUESTS.labels(request.method, endpoint, str(response.status_code)).inc()
        started = getattr(request, "start_time", time.perf_counter())
        LATENCY.labels(request.method, endpoint).observe(time.perf_counter() - started)
        return response

    @app.errorhandler(ValueError)
    def invalid_request(error: ValueError) -> tuple[Response, int]:
        return jsonify(error="invalid_request", message=str(error)), 400

    @app.get("/")
    def dashboard() -> str:
        systems = inventory()
        counts = {
            "total": len(systems),
            "compliant": sum(system["status"] == "compliant" for system in systems),
            "patch_required": sum(system["status"] == "patch_required" for system in systems),
            "stale": sum(system["status"] == "stale" for system in systems),
        }
        return render_template(
            "dashboard.html",
            systems=systems,
            counts=counts,
            target_version=str(target_version()),
            patch_requests=service_store().list_patch_requests(),
        )

    @app.get("/api/systems")
    def list_systems() -> Response:
        return jsonify(systems=inventory(), target_version=str(target_version()))

    @app.post("/systems")
    def register_system() -> tuple[Response, int]:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")

        hostname = _required_string(payload, "hostname")
        platform = _required_string(payload, "platform")
        installed_version = _required_string(payload, "installed_version")
        _validated_version(installed_version, "installed_version")

        system = service_store().register(hostname, platform, installed_version)
        return jsonify(system.as_dict()), 201

    @app.get("/systems/<system_id>")
    def get_system(system_id: str) -> tuple[Response, int] | Response:
        system = service_store().get(system_id)
        if system is None:
            return jsonify(error="not_found", message="system is not registered"), 404
        status = _system_status(
            system,
            target_version(),
            timedelta(minutes=app.config["STALE_AFTER_MINUTES"]),
        )
        return jsonify(**system.as_dict(), status=status)

    @app.post("/systems/<system_id>/check-ins")
    def check_in(system_id: str) -> tuple[Response, int] | Response:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        installed_version = _required_string(payload, "installed_version")
        _validated_version(installed_version, "installed_version")
        system = service_store().check_in(system_id, installed_version)
        if system is None:
            return jsonify(error="not_found", message="system is not registered"), 404
        return jsonify(system.as_dict())

    @app.get("/systems/<system_id>/patch-status")
    def patch_status(system_id: str) -> tuple[Response, int] | Response:
        system = service_store().get(system_id)
        if system is None:
            return jsonify(error="not_found", message="system is not registered"), 404

        target = request.args.get("target_version", app.config["TARGET_VERSION"]).strip()
        installed_version = Version(system.installed_version)
        requested_target = _validated_version(target, "target_version")

        return jsonify(
            system_id=system.id,
            hostname=system.hostname,
            installed_version=str(installed_version),
            target_version=str(requested_target),
            patch_required=installed_version < requested_target,
        )

    @app.post("/systems/<system_id>/patch-requests")
    def request_patch(system_id: str) -> tuple[Response, int]:
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        target = str(payload.get("target_version", app.config["TARGET_VERSION"])).strip()
        requested_target = _validated_version(target, "target_version")
        patch_request = service_store().request_patch(system_id, str(requested_target))
        if patch_request is None:
            return jsonify(error="not_found", message="system is not registered"), 404
        PATCH_REQUESTS.inc()
        return jsonify(patch_request.as_dict()), 202

    @app.get("/health/live")
    def liveness() -> Response:
        return jsonify(status="alive")

    @app.get("/health/ready")
    def readiness() -> Response:
        return jsonify(status="ready")

    @app.get("/version")
    def version() -> Response:
        return jsonify(
            service="system-registration-service",
            version=app.config["SERVICE_VERSION"],
            git_sha=app.config["GIT_SHA"],
            environment=app.config["ENVIRONMENT"],
        )

    @app.get("/metrics")
    def metrics() -> Response:
        inventory()
        return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()

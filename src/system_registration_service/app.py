import os
import time
from collections.abc import Mapping
from typing import Any

from flask import Flask, Response, jsonify, request
from packaging.version import InvalidVersion, Version
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from system_registration_service.store import SystemStore

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


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def create_app(store: SystemStore | None = None) -> Flask:
    app = Flask(__name__)
    app.config["STORE"] = store or SystemStore()
    app.config["SERVICE_VERSION"] = os.getenv("SERVICE_VERSION", "0.1.0")
    app.config["GIT_SHA"] = os.getenv("GIT_SHA", "local")
    app.config["ENVIRONMENT"] = os.getenv("ENVIRONMENT", "development")

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
    def service_identity() -> Response:
        return jsonify(
            service="system-registration-service",
            purpose="Register systems and evaluate patch compliance",
        )

    @app.post("/systems")
    def register_system() -> tuple[Response, int]:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")

        hostname = _required_string(payload, "hostname")
        platform = _required_string(payload, "platform")
        installed_version = _required_string(payload, "installed_version")
        try:
            Version(installed_version)
        except InvalidVersion as error:
            raise ValueError("installed_version must be a valid software version") from error

        system = app.config["STORE"].register(hostname, platform, installed_version)
        return jsonify(system.as_dict()), 201

    @app.get("/systems/<system_id>")
    def get_system(system_id: str) -> tuple[Response, int] | Response:
        system = app.config["STORE"].get(system_id)
        if system is None:
            return jsonify(error="not_found", message="system is not registered"), 404
        return jsonify(system.as_dict())

    @app.get("/systems/<system_id>/patch-status")
    def patch_status(system_id: str) -> tuple[Response, int] | Response:
        system = app.config["STORE"].get(system_id)
        if system is None:
            return jsonify(error="not_found", message="system is not registered"), 404

        target = request.args.get("target_version", "").strip()
        if not target:
            raise ValueError("target_version query parameter is required")
        try:
            installed_version = Version(system.installed_version)
            target_version = Version(target)
        except InvalidVersion as error:
            raise ValueError("target_version must be a valid software version") from error

        return jsonify(
            system_id=system.id,
            hostname=system.hostname,
            installed_version=str(installed_version),
            target_version=str(target_version),
            patch_required=installed_version < target_version,
        )

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
        return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()

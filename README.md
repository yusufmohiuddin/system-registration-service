# System Registration Service

A small Flask API that registers managed systems and evaluates whether their
installed software version meets an approved patch target.

## Business use case

Operations clients register a hostname, platform, and installed version. An
authorized caller can retrieve that registration and ask whether a newer target
version requires patching. The current implementation uses in-memory storage to
keep the platform-onboarding demonstration bounded; production persistence and
authentication are explicit future capabilities.

## Run locally

```bash
uv sync
uv run flask --app system_registration_service.app:app run --port 8080
```

Register and evaluate a system:

```bash
curl -sS -X POST http://localhost:8080/systems \
  -H 'Content-Type: application/json' \
  -d '{"hostname":"capsule-17","platform":"linux","installed_version":"1.2.0"}'

curl -sS 'http://localhost:8080/systems/SYSTEM_ID/patch-status?target_version=1.3.0'
```

Operational endpoints are `/health/live`, `/health/ready`, `/version`, and
`/metrics`.

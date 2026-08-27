# System Registration Service

A small Flask service with an operations dashboard that registers managed
systems, tracks check-ins, evaluates patch compliance, and records approved
patch intent.

## Business use case

Operations clients register a hostname, platform, and installed version. An
authorized caller can retrieve that registration and ask whether a newer target
version requires patching. Operators can see compliant, patch-required, and
stale systems on the dashboard and queue a patch request for execution by a
separately authenticated agent.

The current implementation uses in-memory storage to keep the platform-onboarding
demonstration bounded. Production persistence, authentication, agent identity,
signed commands, and patch execution are explicit future capabilities.

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
`/metrics`. Open `http://localhost:8080/` for the dashboard.

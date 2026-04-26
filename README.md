# Stake Quantum

Stake Quantum is moving toward a three-part architecture for low-latency Stake code distribution and backend claiming:

- `control_plane/`: Django control plane and admin
- `api/`: Go runtime gateway
- `solver/`: Python token solver service

This worktree currently implements the phase 1 foundation only.

## Phase 1 Foundation

Phase 1 adds the control and runtime plumbing that the later claim system will build on:

- Django control plane under `control_plane/`
- PostgreSQL-backed backend claim accounts
- Redis runtime sync for enabled accounts
- Go runtime hot enabled-account cache

### What is included

- durable `BackendClaimAccount` model in Django
- admin actions to enable and disable backend accounts
- Redis runtime account payload sync on enable
- Redis runtime cleanup and lifecycle events on disable
- Go startup preload of enabled accounts from Redis
- Go subscription to `events:accounts`
- Go `/health` visibility for enabled account count

### What is not included yet

Phase 1 does not yet implement:

- per-account token warming
- backend claim fanout using warm tokens
- websocket client dashboard pages
- claim history persistence and stats pages
- full browser client management UI

## Current Architecture

### Control Plane

The Django control plane is the durable source of truth for backend claim accounts.

It owns:

- account CRUD
- enable and disable workflows
- PostgreSQL persistence
- syncing enabled accounts into Redis runtime state

### Go Runtime

The Go runtime currently:

- accepts claim jobs over HTTP
- verifies Redis connectivity
- preloads enabled backend accounts from Redis during startup
- keeps enabled account payloads hot in memory
- listens for `events:accounts` updates so runtime state stays fresh

### Python Solver

The solver service still contains the earlier token-solving foundation. The final per-account warm-token architecture will come in a later phase.

## Runtime Keys

Phase 1 uses these Redis runtime keys:

- `runtime:accounts:enabled`
- `runtime:account:{account_id}`
- `events:accounts`

## Requirements

- PostgreSQL instance for the Django control plane
- Redis instance for runtime state and events
- Go toolchain for local gateway builds
- Python 3.12+ for the control plane and solver

## Configuration

### Control Plane

| Variable | Description |
|----------|-------------|
| `DJANGO_SECRET_KEY` | Django secret key |
| `DJANGO_DEBUG` | Enable Django debug mode |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated allowed hosts |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins |
| `DATABASE_URL` | Preferred PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |

### Go Runtime

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_URL` | Preferred Redis connection string | `` |
| `REDIS_HOST` | Redis hostname | `` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_PASSWORD` | Redis password | `` |
| `QUEUE_NAME` | Redis queue for claim jobs | `claim_queue` |
| `PORT` | Fiber server port | `3000` |

### Solver

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_URL` | Preferred Redis connection string | `` |
| `NODE_ID` | Solver node identifier | `node-default` |
| `CLAIM_CURRENCY` | Currency for claims | `usdt` |
| `CLAIM_RETRIES` | Number of retry attempts | `3` |
| `CAMOFOX_BINARY_PATH` | Optional Camofox binary path | `` |
| `USE_STEALTH` | Enable `playwright-stealth` | `true` |

## Local Verification

The phase 1 foundation should verify with:

```bash
cd control_plane
python manage.py check
python manage.py test runtime.tests -v 2

cd ../api
go build ./...
```

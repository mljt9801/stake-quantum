# Stake Quantum Control Plane Design

Date: 2026-04-20

## Goal

Build a low-latency Stake code distribution and backend claim system with:

- one admin dashboard that controls everything
- websocket broadcast to all connected browser userscript clients
- backend claims for all enabled server-side accounts in parallel
- per-account warm Turnstile token pools maintained continuously
- PostgreSQL as the durable source of truth
- Redis as the runtime state and coordination layer

The highest priority is lowest possible claim latency for enabled backend accounts.

## Final Architecture

The system is composed of three runtime components with one central dashboard:

1. Django control plane
2. Go runtime service
3. Python solver service

The Django control plane is the only admin UI. It manages accounts, websocket client visibility, claim history, and stats.

### Django Control Plane

Responsibilities:

- backend account CRUD
- enable and disable backend claim accounts
- store durable account records in PostgreSQL
- store claim history and stats in PostgreSQL
- display websocket client status
- sync enabled runtime account data into Redis
- publish account change events to Redis

This service is the operator-facing system of record.

### Go Runtime Service

Responsibilities:

- receive codes from existing external sources
- broadcast codes to all connected websocket userscript clients
- track websocket client presence
- receive backend claim events
- keep enabled account runtime data hot in memory
- consume warm tokens from Redis per account
- execute Stake GraphQL claim requests for all enabled accounts in parallel
- write claim results for persistence

This service owns the low-latency hot path.

### Python Solver Service

Responsibilities:

- maintain per-account warm Turnstile token pools
- immediately warm token pools when an account is enabled
- keep two active tokens available per enabled account
- refill pools when tokens are consumed or near expiry
- generate tokens using account-specific identity

This service does not execute the final claim request. It only produces warm tokens for backend accounts.

## Data Ownership

### PostgreSQL

PostgreSQL is the durable source of truth for:

- backend claim accounts
- claim history
- aggregate stats inputs
- optional websocket client historical metadata

### Redis

Redis stores runtime and coordination state:

- enabled backend account cache
- per-account token pools
- websocket client presence
- account enabled and disabled events
- account update events
- incoming code events

### Go Service Memory

The Go runtime keeps enabled backend accounts hot in memory for the lowest latency:

- account identity and config
- token pool readiness metadata
- websocket connection registry

The hot path must not require reloading all enabled accounts from Redis or PostgreSQL when a code arrives.

## Backend Account Model

Each backend claim account stores:

- id
- label
- username
- cookies_json
- x_access_token
- user_agent
- proxy_url nullable
- is_enabled
- is_active
- last_warm_at nullable
- last_claim_at nullable
- last_success_at nullable
- last_error nullable
- created_at
- updated_at

Rules:

- proxy is optional
- if proxy exists, both token solving and final claim request use the same proxy
- disabling an account removes it from Redis runtime state but does not delete it from PostgreSQL
- enabling an account makes it eligible for all incoming backend claims

## Token Pool Model

Each enabled backend account has its own token pool.

Pool target:

- two warm tokens per enabled account

Refill triggers:

- token consumed
- token near expiry
- pool size below two
- account newly enabled

Critical rule:

- token pools are per account only
- there is no global shared token cache

Each token must be generated with the account's effective runtime identity:

- cookies
- user agent
- optional proxy

## Always-Hot Enabled Accounts

Enabled backend accounts must be ready before a code arrives.

Enable flow:

1. operator enables account in Django
2. Django updates PostgreSQL
3. Django writes the runtime account payload into Redis
4. Django publishes an account enabled event
5. Go runtime updates its in-memory enabled account map
6. Python solver starts warming tokens for the account immediately
7. the account becomes ready once the token pool reaches the target

Disable flow:

1. operator disables account in Django
2. Django updates PostgreSQL
3. Django removes the account from Redis runtime state
4. Django publishes an account disabled event
5. Go runtime removes the account from memory
6. Python solver stops warming tokens for the account
7. Redis token pool for that account is discarded

Runtime account data is hot in memory inside the Go runtime. The code-arrival hot path should only iterate the in-memory enabled account map.

## Code Arrival Flow

When a code arrives from existing external sources:

1. Go runtime receives the code
2. Go runtime immediately broadcasts the code to all connected websocket userscript clients
3. Go runtime immediately starts backend claim fanout for all enabled backend accounts
4. for each enabled account, in parallel:
   - pop one warm token from that account's Redis token pool
   - submit a Stake GraphQL claim using the account's cookies, x-access-token, user-agent, and optional proxy
5. persist claim results
6. background token warming refills any consumed token slots

Broadcast and backend claim execution always happen in parallel. Neither path blocks the other.

## Runtime Communication

### Django to Go

Via Redis:

- account enabled
- account disabled
- account updated

Go uses these events to refresh its in-memory enabled account map.

### Django to Python

Via Redis:

- account enabled
- account disabled
- account updated

Python uses these events to begin or stop token warming for account pools.

### Go to Python

Go does not need Python to claim. Python only keeps token pools ready.

Go reads token pool state from Redis and consumes tokens directly.

### Go to Django

Go writes:

- claim results
- websocket client presence state
- optional aggregate counters or events

Django reads this data for dashboard display and persistent storage workflows.

## Redis Runtime Layout

Suggested runtime keys:

- `runtime:accounts:enabled`
  - set of enabled account ids
- `runtime:account:{account_id}`
  - cached account payload
- `runtime:tokens:{account_id}`
  - list or sorted structure of warm tokens for account
- `runtime:tokens:meta:{account_id}`
  - token pool health metadata
- `runtime:clients:{client_id}`
  - client presence metadata
- `events:accounts`
  - account lifecycle pub/sub or stream
- `events:codes`
  - incoming code events if needed

The exact Redis data structure can be chosen during implementation, but the key principle is hot account lookup plus per-account token pools.

## Claim Execution Rules

For each enabled account, the Go runtime should send the GraphQL claim request with:

- stored cookies
- stored x-access-token
- stored user-agent
- optional proxy
- one fresh warm token from that account's token pool

If a token pool is empty:

- fail that account fast, or
- optionally allow an emergency on-demand token request later

The initial implementation should prefer fail-fast plus dashboard visibility to preserve latency guarantees for healthy accounts.

## WebSocket Client Management

The Go runtime owns websocket connections and pushes code messages to all connected userscript clients.

It should maintain runtime client presence with fields like:

- client_id
- connected boolean
- last_seen_at
- ip or remote address if available
- optional user agent
- optional version or label

Django reads Redis presence state and presents websocket client visibility in one dashboard page.

## Dashboard Scope

The Django control plane should provide four operator pages:

### Accounts

- list backend claim accounts
- create and edit accounts
- edit cookies
- edit x-access-token
- edit user-agent
- set optional proxy
- enable and disable accounts
- show token pool health
- show last success and last error

### Claim History

- code
- account
- success or failure
- amount and currency when successful
- error message
- latency
- timestamp

### Stats

- total claims
- success rate
- per-account success rate
- recent failures
- token pool health summary
- recent code activity

### WebSocket Clients

- currently connected clients
- last seen
- online or offline
- available metadata

The dashboard is operations-only. It does not accept manual code submission.

## Error Handling

- one websocket client failing or disconnecting does not block other clients
- one backend account failing does not block claims for any other account
- missing cookies or x-access-token records a per-account failure
- token pool depletion affects only the corresponding account
- missing Redis event should be recoverable with periodic reconciliation
- PostgreSQL outage degrades dashboard and persistence, but runtime may continue temporarily
- token generation failures should surface in account and token pool health views

## Security and Secrets

Account secrets must not be hardcoded in source files.

Sensitive values include:

- cookies_json
- x-access-token
- proxy credentials
- database credentials
- Redis credentials

Secrets should be stored in:

- PostgreSQL for account-owned session data
- environment variables for service credentials

The existing hardcoded secret patterns in earlier repos should not be carried forward.

## Implementation Order

1. create Django control plane project with PostgreSQL models
2. implement backend account CRUD
3. implement enable and disable workflows with Redis sync
4. implement account lifecycle events in Redis
5. refactor Go runtime to hold enabled accounts hot in memory
6. implement websocket client presence tracking into Redis
7. implement Python per-account token warmer and per-account token pools
8. implement Go backend claim fanout using warm per-account tokens
9. implement claim history persistence
10. implement dashboard pages for accounts, claim history, stats, and websocket clients

## Non-Goals for Initial Version

- manual code submission through the dashboard
- user-tier routing logic
- third-party Turnstile solving providers
- a custom SPA frontend
- multi-region distributed orchestration

The initial version should optimize for correctness, observability, and backend claim latency.

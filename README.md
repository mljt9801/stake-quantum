# Stake Quantum - Distributed Solver Grid

A high-performance, distributed Cloudflare Turnstile solver for Stake.com drop claims.

## Architecture
- **Solver Nodes**: Python/Playwright workers running on Railway, VPS, or Home Servers.
- **Token Cache**: 2-token warm pool strategy for instant claim execution.
- **Central Command**: Go API server managing Redis queues and user requests.
- **Stealth Mode**: Uses `playwright-stealth` by default for better evasion (Camofox optional).

## Quick Start

### 1. Deploy Solver Node
```bash
cd solver
docker build -t stake-solver .
docker run -d --env-file .env stake-solver
```

### 2. Deploy API Server
```bash
cd api
docker build -t stake-api .
docker run -d --env-file .env stake-api
```

## Scaling
Simply deploy the `solver` Docker image to multiple machines (Railway, VPS, Home). All nodes will automatically connect to the central Redis queue and start processing claims.

## Requirements
- **Redis instance** (Railway Redis recommended)
- **1GB+ RAM** per solver node (for browser instances)
- **Camofox (Optional)**: For highest success rates, download the Camofox binary and set `CAMOFOX_BINARY_PATH` in your environment. If not set, the solver falls back to standard Firefox with `playwright-stealth`.

## Configuration
Set these environment variables on **both** API and Solver services:

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_HOST` | Redis hostname (e.g., `redis-12345.upstash.io`) | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_PASSWORD` | Redis password (if any) | `` |
| `REDIS_URL` | **Alternative**: Full Redis URL (e.g., `redis://:password@host:port`) | `` |
| `QUEUE_NAME` | Name of the Redis queue for claims | `claim_queue` |
| `RESULT_CHANNEL` | Redis channel for results | `claim_results` |
| `NODE_ID` | Unique ID for this solver node | `node-default` |
| `CLAIM_CURRENCY` | Currency for claims (e.g., `usdt`, `btc`) | `usdt` |
| `CLAIM_RETRIES` | Number of retry attempts per claim | `3` |
| `CAMOFOX_BINARY_PATH` | Path to Camofox binary (optional) | `` |
| `USE_STEALTH` | Enable playwright-stealth | `true` |

### Example `.env` File
```env
REDIS_HOST=redis-12345.upstash.io
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password
QUEUE_NAME=claim_queue
NODE_ID=solver-node-1
CLAIM_CURRENCY=usdt
```
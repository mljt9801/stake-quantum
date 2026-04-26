# Stake Quantum - Distributed Solver Grid

A high-performance, distributed Cloudflare Turnstile solver for Stake.com drop claims.

## Architecture
The system supports two distinct claim modes:
1. **API Clients (Server-Side)**: You send a code via HTTP → **Your Python Solvers** claim it using stored cookies/proxies.
2. **Browser Clients (User-Side)**: Users connect via WebSocket → **Their Browsers** receive the code and claim it locally.

## Quick Start

### 1. Deploy Solver Node (For API Clients)
```bash
cd solver
docker build -t stake-solver .
docker run -d --env-file .env stake-solver
```
*This node listens to the Redis queue and claims codes on behalf of your accounts.*

### 2. Deploy API Server
```bash
cd api
docker build -t stake-api .
docker run -d --env-file .env stake-api
```
*This server routes HTTP requests to the solver and handles WebSocket connections for browser clients.*

## Scaling
- **API Clients**: Deploy more `solver` nodes to increase claim speed for your own accounts.
- **Browser Clients**: Users install the Userscript; no server scaling needed.

## Requirements
- **Redis instance** (Railway Redis recommended)
- **1GB+ RAM** per solver node (for browser instances)
- **Camofox (Optional)**: For highest success rates, download the Camofox binary and set `CAMOFOX_BINARY_PATH`. If not set, the solver falls back to standard Firefox with `playwright-stealth`.

## Configuration
Set these environment variables on **both** API and Solver services:

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_HOST` | Redis hostname (e.g., `redis-12345.upstash.io`) | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_PASSWORD` | Redis password (if any) | `` |
| `REDIS_URL` | **Alternative**: Full Redis URL (e.g., `redis://:password@host:port`) | `` |
| `QUEUE_NAME` | Name of the Redis queue for claims (API Clients) | `claim_queue` |
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

## Usage

### For API Clients (Server-Side Claims)
Use this if you want **your servers** to claim drops for your accounts.

1. **Store Account Data**: Save cookies, user-agent, and proxy for each account in Redis:
   ```bash
   # Example: Save account data for user_id "account_123"
   redis-cli SET "account:account_123" '{
     "cookies": [{"name": "session_id", "value": "xyz..."}],
     "user_agent": "Mozilla/5.0...",
     "proxy_url": "http://proxy:port",
     "token": "x-access-token..."
   }'
   ```

2. **Send a Claim Request**:
   ```bash
   curl -X POST http://localhost:3000/claim \
     -H "Content-Type: application/json" \
     -d '{"user_id": "account_123", "code": "SUPERDROP24"}'
   ```
   *The solver will fetch the account data, solve the captcha, and claim the code.*

### For Browser Clients (User-Side Claims)
Use this if you want **users** to claim drops on their own browsers.

1. **Install the Userscript**:
   - Copy the code from `client/userscript.js`.
   - Install it in **Tampermonkey** or **Greasemonkey**.
   - Open `https://stake.com/`.

2. **Broadcast a Code**:
   ```bash
   curl -X POST http://localhost:3000/broadcast \
     -H "Content-Type: application/json" \
     -d '{"code": "SUPERDROP24"}'
   ```
   *All connected browser clients will receive the code and attempt to claim it immediately.*

## Multi-Account Support
The solver is designed to handle **multiple accounts** simultaneously.
- Each account must be stored in Redis with the key `account:{user_id}`.
- The solver fetches the specific `cookies`, `proxy`, and `user_agent` for that `user_id` before claiming.
- Ensure your Redis database is populated with valid session data for all accounts you wish to use.

## Troubleshooting
- **"Account not found"**: Ensure you have saved account data to Redis using the `account:{user_id}` key format.
- **"Turnstile solve failed"**: Check if `CAMOFOX_BINARY_PATH` is set correctly or try enabling `USE_STEALTH=true`.
- **"Redis connection failed"**: Verify `REDIS_HOST`, `REDIS_PORT`, and `REDIS_PASSWORD` are correct.
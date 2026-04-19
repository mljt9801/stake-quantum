import os
import re
from urllib.parse import urlparse

# --- Redis Configuration ---
# Support full URL (e.g., redis://user:pass@host:port/db) or separate vars
REDIS_URL = os.getenv("REDIS_URL", "")

def parse_redis_url(url: str) -> dict:
    """
    Parse Redis URL supporting various formats:
    - redis://user:pass@host:port/db
    - redis://:pass@host:port (no user)
    - redis://host:port (no auth)
    - rediss://... (SSL/TLS)
    - redis://host:port (no db suffix)
    """
    parsed = urlparse(url)
    
    # Determine port (default 6379 for redis, 6380 for rediss)
    port = parsed.port
    if port is None:
        port = 6380 if parsed.scheme == 'rediss' else 6379
    
    # Extract password from URL
    password = parsed.password if parsed.password else ""
    
    # Extract database from path
    db = 0
    if parsed.path:
        # Path might be '/0' or just ''
        path_parts = parsed.path.strip('/').split('/')
        if path_parts and path_parts[0].isdigit():
            db = int(path_parts[0])
    
    return {
        'host': parsed.hostname or 'localhost',
        'port': port,
        'password': password,
        'db': db,
        'ssl': parsed.scheme == 'rediss'
    }

if REDIS_URL:
    try:
        config = parse_redis_url(REDIS_URL)
        REDIS_HOST = config['host']
        REDIS_PORT = config['port']
        REDIS_PASSWORD = config['password']
        REDIS_DB = config['db']
        REDIS_SSL = config['ssl']
    except Exception as e:
        # Log warning and fallback to individual vars
        import logging
        logging.warning(f"Failed to parse REDIS_URL '{REDIS_URL}': {e}. Falling back to individual config vars.")
        REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
        REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
        REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
        REDIS_DB = 0
        REDIS_SSL = False
else:
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
    REDIS_DB = 0
    REDIS_SSL = False

QUEUE_NAME = os.getenv("QUEUE_NAME", "claim_queue")
RESULT_CHANNEL = os.getenv("RESULT_CHANNEL", "claim_results")

# --- Node Configuration ---
NODE_ID = os.getenv("NODE_ID", "node-default")

# --- Solver Configuration ---
CAMOFOX_BINARY_PATH = os.getenv("CAMOFOX_BINARY_PATH", "")
SOLVER_TIMEOUT = int(os.getenv("SOLVER_TIMEOUT", 30))
USE_STEALTH = os.getenv("USE_STEALTH", "true").lower() == "true"

# --- Claim Configuration ---
CLAIM_CURRENCY = os.getenv("CLAIM_CURRENCY", "usdt").lower()
CLAIM_RETRIES = int(os.getenv("CLAIM_RETRIES", 3))
CLAIM_BACKOFF_BASE = int(os.getenv("CLAIM_BACKOFF_BASE", 2)) # seconds

# --- Stake Configuration ---
STAKE_BASE_URL = "https://stake.com"
TURNSTILE_SITE_KEY = "0x4AAAAAAAGD4gMGOTFnvupz"
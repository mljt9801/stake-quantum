# Stake Quantum Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the new Django control plane, PostgreSQL-backed backend account model, Redis runtime account sync, and the Go runtime's hot enabled-account cache to `stake-quantum` without breaking the current websocket broadcast path.

**Architecture:** This phase introduces the durable source-of-truth layer and runtime account distribution only. Django owns account CRUD and enable/disable state in PostgreSQL, mirrors enabled accounts into Redis, and publishes account lifecycle events; the Go runtime subscribes to those events and keeps enabled accounts hot in memory while preserving its existing websocket broadcast responsibilities.

**Tech Stack:** Django, PostgreSQL, Redis, Go/Fiber, Python tooling for local development

---

## Scope Decomposition

The full spec covers multiple subsystems. This plan intentionally implements only the foundation slice:

1. new Django control plane app inside this repo
2. PostgreSQL-backed backend account persistence
3. Redis runtime cache and account lifecycle events
4. Go runtime support for hot enabled-account state
5. documentation and verification for the new foundation

Follow-on plans should cover:

- Python per-account token warmer
- Go backend claim execution using warm tokens
- claim history/statistics persistence and dashboard pages
- websocket client management views

## Planned File Structure

### New files and directories

- `control_plane/manage.py`
- `control_plane/control_plane/__init__.py`
- `control_plane/control_plane/asgi.py`
- `control_plane/control_plane/settings.py`
- `control_plane/control_plane/urls.py`
- `control_plane/control_plane/wsgi.py`
- `control_plane/runtime/__init__.py`
- `control_plane/runtime/apps.py`
- `control_plane/runtime/models.py`
- `control_plane/runtime/admin.py`
- `control_plane/runtime/services/__init__.py`
- `control_plane/runtime/services/redis_runtime.py`
- `control_plane/runtime/migrations/0001_initial.py`
- `control_plane/requirements.txt`
- `control_plane/.env.example`

### Existing files to modify

- `README.md`
- `api/go.mod`
- `api/main.go`
- `.gitignore`

### Responsibilities

- `control_plane/control_plane/settings.py`: Django settings, PostgreSQL config, Redis config, installed apps
- `control_plane/runtime/models.py`: backend claim account durable model and validation helpers
- `control_plane/runtime/admin.py`: account management UI including enable/disable actions
- `control_plane/runtime/services/redis_runtime.py`: Redis serialization, enabled-account sync, and event publication
- `api/main.go`: in-memory enabled account cache, Redis event subscriber, runtime account models, and health visibility
- `README.md`: updated architecture, setup, and phase-1 operational instructions

## Task 1: Scaffold the Django Control Plane

**Files:**
- Create: `control_plane/manage.py`
- Create: `control_plane/control_plane/__init__.py`
- Create: `control_plane/control_plane/asgi.py`
- Create: `control_plane/control_plane/settings.py`
- Create: `control_plane/control_plane/urls.py`
- Create: `control_plane/control_plane/wsgi.py`
- Create: `control_plane/runtime/__init__.py`
- Create: `control_plane/runtime/apps.py`
- Create: `control_plane/requirements.txt`
- Create: `control_plane/.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Write the failing bootstrap check list**

Document these expected bootstrap commands before writing code:

```text
python control_plane/manage.py check
python control_plane/manage.py makemigrations --check
python control_plane/manage.py showmigrations
```

Expected initial failures:

- `python` project entrypoint missing
- Django settings module missing
- `runtime` app missing

- [ ] **Step 2: Add control plane dependencies**

Write `control_plane/requirements.txt` with:

```txt
Django==5.1.8
psycopg[binary]==3.2.6
redis==5.0.1
python-dotenv==1.0.1
```

Write `control_plane/.env.example` with:

```env
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
POSTGRES_DB=stake_quantum
POSTGRES_USER=stake_quantum
POSTGRES_PASSWORD=stake_quantum
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
REDIS_URL=redis://127.0.0.1:6379/0
```

- [ ] **Step 3: Create the Django project skeleton**

Create `control_plane/manage.py`:

```python
#!/usr/bin/env python
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "control_plane.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

Create `control_plane/control_plane/settings.py` with:

```python
from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "runtime",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "control_plane.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "control_plane.wsgi.application"
ASGI_APPLICATION = "control_plane.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB"),
        "USER": os.getenv("POSTGRES_USER"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
```

Create `control_plane/control_plane/urls.py`:

```python
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
```

Create `control_plane/control_plane/asgi.py` and `control_plane/control_plane/wsgi.py`:

```python
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "control_plane.settings")
application = get_asgi_application()
```

```python
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "control_plane.settings")
application = get_wsgi_application()
```

Create `control_plane/runtime/apps.py`:

```python
from django.apps import AppConfig


class RuntimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "runtime"
```

- [ ] **Step 4: Ignore local control plane environment files**

Update `.gitignore` by appending:

```gitignore
control_plane/.env
control_plane/.venv/
control_plane/__pycache__/
control_plane/**/__pycache__/
```

- [ ] **Step 5: Run bootstrap checks**

Run:

```powershell
python control_plane/manage.py check
```

Expected:

- either `System check identified no issues`
- or a clear local environment error such as missing Django/PostgreSQL or required environment variables, but not missing project modules

- [ ] **Step 6: Commit**

```bash
git add .gitignore control_plane/manage.py control_plane/control_plane control_plane/runtime/__init__.py control_plane/runtime/apps.py control_plane/requirements.txt control_plane/.env.example
git commit -m "feat: scaffold django control plane"
```

## Task 2: Add the Durable Backend Account Model

**Files:**
- Create: `control_plane/runtime/models.py`
- Create: `control_plane/runtime/migrations/0001_initial.py`
- Test: `control_plane/runtime/tests.py`

- [ ] **Step 1: Write the failing model test**

Create `control_plane/runtime/tests.py`:

```python
from django.core.exceptions import ValidationError
from django.test import TestCase

from runtime.models import BackendClaimAccount


class BackendClaimAccountTests(TestCase):
    def test_proxy_is_optional(self):
        account = BackendClaimAccount(
            label="acc-1",
            username="tester",
            cookies_json='[{"name":"cf_clearance","value":"abc"}]',
            x_access_token="token-1",
            user_agent="Mozilla/5.0",
            proxy_url="",
            is_enabled=False,
            is_active=True,
        )
        account.full_clean()

    def test_blank_access_token_is_rejected(self):
        account = BackendClaimAccount(
            label="acc-2",
            username="tester-2",
            cookies_json="[]",
            x_access_token="",
            user_agent="Mozilla/5.0",
        )
        with self.assertRaises(ValidationError):
            account.full_clean()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python control_plane/manage.py test runtime.tests.BackendClaimAccountTests -v 2
```

Expected:

- fail with import or model missing errors

- [ ] **Step 3: Write the minimal model**

Create `control_plane/runtime/models.py`:

```python
from django.core.validators import MinLengthValidator
from django.db import models


class BackendClaimAccount(models.Model):
    label = models.CharField(max_length=100, unique=True)
    username = models.CharField(max_length=100)
    cookies_json = models.TextField()
    x_access_token = models.TextField(validators=[MinLengthValidator(1)])
    user_agent = models.TextField(validators=[MinLengthValidator(1)])
    proxy_url = models.TextField(blank=True, default="")
    is_enabled = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_warm_at = models.DateTimeField(null=True, blank=True)
    last_claim_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label"]

    def __str__(self) -> str:
        return self.label
```

Run:

```powershell
python control_plane/manage.py makemigrations runtime
```

Commit the generated migration file as `control_plane/runtime/migrations/0001_initial.py`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python control_plane/manage.py test runtime.tests.BackendClaimAccountTests -v 2
```

Expected:

- both tests pass

- [ ] **Step 5: Commit**

```bash
git add control_plane/runtime/models.py control_plane/runtime/migrations/0001_initial.py control_plane/runtime/tests.py
git commit -m "feat: add backend claim account model"
```

## Task 3: Sync Enabled Accounts into Redis from Django

**Files:**
- Create: `control_plane/runtime/services/__init__.py`
- Create: `control_plane/runtime/services/redis_runtime.py`
- Modify: `control_plane/runtime/admin.py`
- Test: `control_plane/runtime/tests.py`

- [ ] **Step 1: Write the failing sync test**

Append to `control_plane/runtime/tests.py`:

```python
from unittest.mock import patch

from runtime.services.redis_runtime import account_runtime_key, build_runtime_payload


class RuntimeSyncTests(TestCase):
    def test_runtime_payload_contains_optional_proxy_field(self):
        account = BackendClaimAccount.objects.create(
            label="acc-sync",
            username="runtime-user",
            cookies_json="[]",
            x_access_token="token-sync",
            user_agent="Mozilla/5.0",
            proxy_url="",
            is_enabled=True,
        )
        payload = build_runtime_payload(account)
        self.assertEqual(payload["account_id"], account.id)
        self.assertEqual(payload["proxy_url"], "")

    @patch("runtime.services.redis_runtime.get_redis_client")
    def test_sync_enabled_account_writes_hash_and_set(self, client_factory):
        fake = client_factory.return_value
        account = BackendClaimAccount.objects.create(
            label="acc-enabled",
            username="enabled-user",
            cookies_json="[]",
            x_access_token="token-enabled",
            user_agent="Mozilla/5.0",
            is_enabled=True,
        )
        from runtime.services.redis_runtime import sync_account_to_runtime

        sync_account_to_runtime(account)

        fake.set.assert_called_once()
        fake.sadd.assert_called_once_with("runtime:accounts:enabled", str(account.id))
        fake.publish.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python control_plane/manage.py test runtime.tests.RuntimeSyncTests -v 2
```

Expected:

- fail because runtime sync service is missing

- [ ] **Step 3: Implement Redis runtime sync service**

Create `control_plane/runtime/services/redis_runtime.py`:

```python
import json

import redis
from django.conf import settings


def get_redis_client():
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def account_runtime_key(account_id: int) -> str:
    return f"runtime:account:{account_id}"


def build_runtime_payload(account):
    return {
        "account_id": account.id,
        "label": account.label,
        "username": account.username,
        "cookies_json": account.cookies_json,
        "x_access_token": account.x_access_token,
        "user_agent": account.user_agent,
        "proxy_url": account.proxy_url or "",
        "is_enabled": account.is_enabled,
        "is_active": account.is_active,
    }


def sync_account_to_runtime(account) -> None:
    client = get_redis_client()
    payload = json.dumps(build_runtime_payload(account))
    client.set(account_runtime_key(account.id), payload)
    client.sadd("runtime:accounts:enabled", str(account.id))
    client.publish("events:accounts", json.dumps({"type": "account_enabled", "account_id": account.id}))


def remove_account_from_runtime(account_id: int) -> None:
    client = get_redis_client()
    client.delete(account_runtime_key(account_id))
    client.srem("runtime:accounts:enabled", str(account_id))
    client.delete(f"runtime:tokens:{account_id}")
    client.delete(f"runtime:tokens:meta:{account_id}")
    client.publish("events:accounts", json.dumps({"type": "account_disabled", "account_id": account_id}))
```

Create `control_plane/runtime/services/__init__.py`:

```python
from .redis_runtime import remove_account_from_runtime, sync_account_to_runtime

__all__ = ["remove_account_from_runtime", "sync_account_to_runtime"]
```

Create `control_plane/runtime/admin.py`:

```python
from django.contrib import admin

from runtime.models import BackendClaimAccount
from runtime.services.redis_runtime import remove_account_from_runtime, sync_account_to_runtime


@admin.register(BackendClaimAccount)
class BackendClaimAccountAdmin(admin.ModelAdmin):
    list_display = ("label", "username", "is_enabled", "is_active", "updated_at")
    list_filter = ("is_enabled", "is_active")
    search_fields = ("label", "username")
    actions = ("enable_accounts", "disable_accounts")

    @admin.action(description="Enable selected accounts")
    def enable_accounts(self, request, queryset):
        for account in queryset:
            account.is_enabled = True
            account.save(update_fields=["is_enabled", "updated_at"])
            sync_account_to_runtime(account)

    @admin.action(description="Disable selected accounts")
    def disable_accounts(self, request, queryset):
        for account in queryset:
            account.is_enabled = False
            account.save(update_fields=["is_enabled", "updated_at"])
            remove_account_from_runtime(account.id)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python control_plane/manage.py test runtime.tests.RuntimeSyncTests -v 2
```

Expected:

- both sync tests pass

- [ ] **Step 5: Commit**

```bash
git add control_plane/runtime/services/__init__.py control_plane/runtime/services/redis_runtime.py control_plane/runtime/admin.py control_plane/runtime/tests.py
git commit -m "feat: sync enabled accounts into redis runtime"
```

## Task 4: Add Go Runtime Support for Hot Enabled Accounts

**Files:**
- Modify: `api/main.go`
- Modify: `api/go.mod`

- [ ] **Step 1: Write the failing behavior note**

Before editing Go code, define these expected runtime behaviors:

- load enabled accounts from Redis during startup
- subscribe to `events:accounts`
- keep account payloads hot in memory
- expose enabled-account count from `/health`

Current code lacks all four behaviors.

- [ ] **Step 2: Add runtime account structures and preload logic**

Modify `api/main.go` to add:

```go
type RuntimeAccount struct {
    AccountID    int    `json:"account_id"`
    Label        string `json:"label"`
    Username     string `json:"username"`
    CookiesJSON  string `json:"cookies_json"`
    XAccessToken string `json:"x_access_token"`
    UserAgent    string `json:"user_agent"`
    ProxyURL     string `json:"proxy_url"`
    IsEnabled    bool   `json:"is_enabled"`
    IsActive     bool   `json:"is_active"`
}
```

and global state:

```go
var runtimeAccounts = map[int]RuntimeAccount{}
var runtimeAccountsMu sync.RWMutex
```

Add helper functions:

```go
func loadEnabledAccounts() error
func upsertRuntimeAccount(account RuntimeAccount)
func removeRuntimeAccount(accountID int)
func subscribeAccountEvents()
```

Use Redis keys:

- `runtime:accounts:enabled`
- `runtime:account:{id}`
- channel `events:accounts`

- [ ] **Step 3: Update health output to show runtime readiness**

Update `/health` response in `api/main.go` to include:

```go
"enabled_accounts": enabledAccountCount(),
"active_clients": len(hub.clients),
```

where:

```go
func enabledAccountCount() int {
    runtimeAccountsMu.RLock()
    defer runtimeAccountsMu.RUnlock()
    return len(runtimeAccounts)
}
```

- [ ] **Step 4: Initialize preload and subscription during startup**

In `main()`, after Redis ping succeeds, call:

```go
if err := loadEnabledAccounts(); err != nil {
    log.Fatalf("Failed to preload runtime accounts: %v", err)
}
go subscribeAccountEvents()
```

- [ ] **Step 5: Verify build**

Run:

```powershell
go build ./...
```

from:

```powershell
Set-Location D:\Project\stake-quantum\api
```

Expected:

- build succeeds with no compile errors

- [ ] **Step 6: Commit**

```bash
git add api/main.go api/go.mod api/go.sum
git commit -m "feat: keep enabled backend accounts hot in go runtime"
```

## Task 5: Document the New Foundation Workflow

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add architecture and setup documentation**

Update `README.md` to include:

- control plane component overview
- PostgreSQL requirement
- Redis runtime account sync
- account enable/disable lifecycle
- note that Python token warming and backend claim fanout are not yet implemented in this phase

Add a section like:

```md
## Phase 1 Foundation

This phase adds:

- Django control plane under `control_plane/`
- PostgreSQL-backed backend claim accounts
- Redis runtime sync for enabled accounts
- Go runtime hot enabled-account cache

Not yet included in phase 1:

- per-account token warming
- backend claim fanout using warm tokens
- claim history dashboard pages
```

- [ ] **Step 2: Verify documentation references actual paths**

Run:

```powershell
Get-Content README.md
```

Expected:

- all referenced folders exist
- commands refer to `control_plane/`, `api/`, and Redis/PostgreSQL correctly

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: describe control plane foundation phase"
```

## Task 6: End-to-End Foundation Verification

**Files:**
- Verify only

- [ ] **Step 1: Run Django checks**

Run:

```powershell
python control_plane/manage.py check
python control_plane/manage.py test runtime.tests -v 2
```

Expected:

- Django check passes
- runtime tests pass

- [ ] **Step 2: Run Go build**

Run:

```powershell
Set-Location D:\Project\stake-quantum\api
go build ./...
```

Expected:

- build succeeds

- [ ] **Step 3: Confirm only intended files changed for phase 1**

Run:

```powershell
& 'C:\Program Files\Git\cmd\git.exe' status --short
```

Expected:

- only control plane foundation files, README, and Go runtime files from this plan are modified or committed

- [ ] **Step 4: Commit verification checkpoint**

```bash
git add .
git commit -m "chore: verify phase 1 foundation"
```

## Self-Review

### Spec Coverage

This plan covers these spec requirements:

- Django control plane introduction
- PostgreSQL as durable source of truth for backend accounts
- Redis runtime account cache
- enable and disable workflows
- Go runtime hot in-memory enabled account map

This plan intentionally does not yet implement:

- Python per-account token warming
- Go backend claim fanout using warm tokens
- websocket client dashboard pages
- claim history persistence and stats pages

Those require follow-on phase plans.

### Placeholder Scan

No `TODO`, `TBD`, or vague implementation-only steps remain in this plan.

### Type Consistency

The plan uses the same field names across Django, Redis, and Go:

- `account_id`
- `cookies_json`
- `x_access_token`
- `user_agent`
- `proxy_url`
- `is_enabled`
- `is_active`

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-20-stake-quantum-phase-1-foundation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

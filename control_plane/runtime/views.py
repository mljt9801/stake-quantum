from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from runtime.models import BackendClaimAccount
from runtime.services.redis_runtime import list_connected_clients, list_token_pool_health


@login_required
def runtime_dashboard(request):
    accounts = BackendClaimAccount.objects.order_by("label")
    connected_clients = list_connected_clients()
    token_health = list_token_pool_health(accounts)

    context = {
        "summary": {
            "account_count": accounts.count(),
            "enabled_accounts": sum(1 for account in accounts if account.is_enabled),
            "connected_clients": len(connected_clients),
        },
        "connected_clients": connected_clients,
        "token_health": token_health,
    }
    return render(request, "runtime/dashboard.html", context)

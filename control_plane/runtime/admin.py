from django.contrib import admin

from runtime.models import BackendClaimAccount
from runtime.services.redis_runtime import remove_account_from_runtime, sync_account_to_runtime


@admin.register(BackendClaimAccount)
class BackendClaimAccountAdmin(admin.ModelAdmin):
    list_display = ("label", "username", "is_enabled", "is_active", "updated_at")
    list_filter = ("is_enabled", "is_active")
    search_fields = ("label", "username")
    actions = ("enable_accounts", "disable_accounts")
    ordering = ("label",)

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

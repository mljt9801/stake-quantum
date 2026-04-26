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

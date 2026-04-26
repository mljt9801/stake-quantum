from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="BackendClaimAccount",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("label", models.CharField(max_length=100, unique=True)),
                ("username", models.CharField(max_length=100)),
                ("cookies_json", models.TextField()),
                (
                    "x_access_token",
                    models.TextField(
                        validators=[django.core.validators.MinLengthValidator(1)]
                    ),
                ),
                (
                    "user_agent",
                    models.TextField(
                        validators=[django.core.validators.MinLengthValidator(1)]
                    ),
                ),
                ("proxy_url", models.TextField(blank=True, default="")),
                ("is_enabled", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("last_warm_at", models.DateTimeField(blank=True, null=True)),
                ("last_claim_at", models.DateTimeField(blank=True, null=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["label"]},
        ),
    ]

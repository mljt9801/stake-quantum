from django.contrib import admin
from django.urls import path
from runtime.views import runtime_dashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("runtime/", runtime_dashboard, name="runtime-dashboard"),
]

from django.contrib import admin
from django.urls import include, path
from .health import health

urlpatterns = [path('healthz/', health, name='health'), path('admin/', admin.site.urls), path('', include('mail.urls'))]

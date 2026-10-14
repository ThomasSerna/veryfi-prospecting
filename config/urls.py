"""Rutas globales y recursos estáticos del servidor local."""

from django.contrib.staticfiles.views import serve
from django.urls import include, path, re_path


urlpatterns = [
    path("", include("core.urls")),
    re_path(r"^static/(?P<path>.*)$", serve, {"insecure": True}),
]

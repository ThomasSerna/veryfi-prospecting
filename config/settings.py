"""Configuración local: una instancia, sin ORM ni cuentas de usuario."""

import os
from pathlib import Path
import secrets

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or secrets.token_urlsafe(48)
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
ROOT_URLCONF = "config.urls"
INSTALLED_APPS = ["core", "django.contrib.staticfiles"]
MIDDLEWARE = [
    "core.middleware.LoopbackMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
}]
DATABASES = {}
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
LANGUAGE_CODE = "es-co"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
PROSPECTING_DB_PATH = Path(os.environ.get("PROSPECTING_DB_PATH", BASE_DIR / "data" / "prospecting.sqlite3"))
PROSPECTING_ACCESS_PATH = Path(os.environ.get("PROSPECTING_ACCESS_PATH", BASE_DIR / "data" / "provider-access.json"))
PROSPECTING_EXCLUSIONS_PATH = Path(os.environ.get("PROSPECTING_EXCLUSIONS_PATH", BASE_DIR / "data" / "exclusions.json"))
PROSPECTING_CONFIG_PATH = Path(os.environ.get("PROSPECTING_CONFIG_PATH", BASE_DIR / "config" / "veryfi.json"))
LOGGING = {"version": 1, "disable_existing_loggers": False, "loggers": {
    "django.request": {"handlers": [], "propagate": False},
}}

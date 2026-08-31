"""Shared Django settings for all environments."""

from datetime import timedelta
from pathlib import Path

import environ


BASE_DIR = Path(__file__).resolve().parents[2]
env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

DATABASES = {"default": env.db("DATABASE_URL")}

AUTH_USER_MODEL = "accounts.User"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.accounts",
    "apps.knowledge",
    "apps.sales",
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

ROOT_URLCONF = "config.urls"

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
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMBEDDING_PROVIDER = env("EMBEDDING_PROVIDER", default="openai_compatible")
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="BAAI/bge-m3")
EMBEDDING_DIMENSIONS = env.int("EMBEDDING_DIMENSIONS", default=1024)
EMBEDDING_API_KEY = env("EMBEDDING_API_KEY", default="")
EMBEDDING_BASE_URL = env("EMBEDDING_BASE_URL", default="")
EMBEDDING_TIMEOUT_SECONDS = env.int("EMBEDDING_TIMEOUT_SECONDS", default=30)
EMBEDDING_MAX_RETRIES = env.int("EMBEDDING_MAX_RETRIES", default=2)
EMBEDDING_BATCH_SIZE = env.int("EMBEDDING_BATCH_SIZE", default=32)

LLM_PROVIDER = env("LLM_PROVIDER", default="deepseek")
LLM_MODEL = env("LLM_MODEL", default="deepseek-v4-flash")
LLM_API_KEY = env("LLM_API_KEY", default="")
LLM_BASE_URL = env("LLM_BASE_URL", default="https://api.deepseek.com")
LLM_TIMEOUT_SECONDS = env.int("LLM_TIMEOUT_SECONDS", default=60)
LLM_MAX_RETRIES = env.int("LLM_MAX_RETRIES", default=2)
LLM_MAX_OUTPUT_TOKENS = env.int("LLM_MAX_OUTPUT_TOKENS", default=1024)
LLM_THINKING_ENABLED = env.bool("LLM_THINKING_ENABLED", default=False)

# Structured solution drafts need more output space than ordinary LLM tasks.
SOLUTION_DRAFT_MAX_OUTPUT_TOKENS = env.int("SOLUTION_DRAFT_MAX_OUTPUT_TOKENS", default=4000)

KNOWLEDGE_MAX_FILE_SIZE_BYTES = env.int(
    "KNOWLEDGE_MAX_FILE_SIZE_BYTES",
    default=20 * 1024 * 1024,
)
KNOWLEDGE_MAX_PDF_PAGES = env.int("KNOWLEDGE_MAX_PDF_PAGES", default=300)
KNOWLEDGE_MAX_CHUNKS = env.int("KNOWLEDGE_MAX_CHUNKS", default=500)
KNOWLEDGE_CHUNK_SIZE = env.int("KNOWLEDGE_CHUNK_SIZE", default=1200)
KNOWLEDGE_CHUNK_OVERLAP = env.int("KNOWLEDGE_CHUNK_OVERLAP", default=150)
KNOWLEDGE_INDEXING_STALE_TIMEOUT_SECONDS = env.int(
    "KNOWLEDGE_INDEXING_STALE_TIMEOUT_SECONDS",
    default=3600,
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "SIGNING_KEY": env("JWT_SIGNING_KEY"),
}

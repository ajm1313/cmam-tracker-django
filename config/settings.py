"""
Django settings for CMAM Tracker project.
"""

from pathlib import Path
from decouple import config
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-this-in-production-12345')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,192.168.0.100,192.168.0.101,10.0.2.2,*').split(',')

# Railway assigns a dynamic public domain via this env var (when present)
_RAILWAY_DOMAIN = config('RAILWAY_PUBLIC_DOMAIN', default='')
if _RAILWAY_DOMAIN and _RAILWAY_DOMAIN not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_RAILWAY_DOMAIN)

# Always trust Railway's own domain suffix regardless of whether
# RAILWAY_PUBLIC_DOMAIN was injected (Django supports wildcard hosts with a
# leading dot).
if '.up.railway.app' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('.up.railway.app')

# Railway's healthcheck uses this hostname
if 'healthcheck.railway.app' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('healthcheck.railway.app')

# CSRF Trusted Origins (for browser preview proxy)
# ponytail: Use .env or wildcard middleware instead of hardcoding ports
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8080',
    'http://127.0.0.1:8080',
    'http://127.0.0.1:3869',
    'https://127.0.0.1:3869',
    'http://localhost:3869',
    'http://127.0.0.1:8654',
    'http://localhost:8654',
    'http://127.0.0.1:8083',
    'http://localhost:8083',
    'http://127.0.0.1:7446',
    'http://127.0.0.1:9246',
]

if _RAILWAY_DOMAIN:
    CSRF_TRUSTED_ORIGINS.append(f'https://{_RAILWAY_DOMAIN}')

# Trust all Railway subdomains regardless of RAILWAY_PUBLIC_DOMAIN detection
CSRF_TRUSTED_ORIGINS.append('https://*.up.railway.app')

# Allow all localhost origins in DEBUG mode
if DEBUG:
    import re
    from django.middleware.csrf import CsrfViewMiddleware
    original_process_view = CsrfViewMiddleware.process_view
    def patched_process_view(self, request, callback, callback_args, callback_kwargs):
        origin = request.META.get('HTTP_ORIGIN', '')
        if re.match(r'^https?://(localhost|127\.0\.0\.1)(:\d+)?$', origin):
            request.META['HTTP_ORIGIN'] = 'http://127.0.0.1:8083'
        return original_process_view(self, request, callback, callback_args, callback_kwargs)
    CsrfViewMiddleware.process_view = patched_process_view

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_filters',
    
    # Local apps
    'apps.core',
    'apps.users',
    'apps.locations',
    'apps.facilities',
    'apps.inventory',
    'apps.cases',
    'apps.api',
]

MIDDLEWARE = [
    'apps.core.middleware.HealthCheckMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'apps.core.middleware.RateLimitMiddleware',  # Rate limiting
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.core.middleware.AuditLogMiddleware',  # Audit logging
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.core.middleware.OverdueVisitSchedulerMiddleware',  # Daily overdue visit push notifications
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
_DATABASE_URL = config('DATABASE_URL', default='')
if _DATABASE_URL:
    # Railway (and other PaaS providers) inject a single DATABASE_URL
    import dj_database_url
    DATABASES = {
        'default': dj_database_url.parse(
            _DATABASE_URL,
            conn_max_age=600,
        )
    }
    DATABASES['default'].setdefault('OPTIONS', {})
    if 'mysql' in DATABASES['default']['ENGINE']:
        DATABASES['default']['OPTIONS'].update({
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'charset': 'utf8mb4',
        })
else:
    _DB_ENGINE = config('DB_ENGINE', default='django.db.backends.mysql')
    _DB_CONFIG: dict = {
        'ENGINE': _DB_ENGINE,
        'NAME': config('DB_NAME', default='cmam_tracker'),
    }
    if 'sqlite' not in _DB_ENGINE:
        _DB_CONFIG.update({
            'USER': config('DB_USER', default='cmam_user'),
            'PASSWORD': config('DB_PASSWORD', default='cmam_password'),
            'HOST': config('DB_HOST', default='db'),
            'PORT': config('DB_PORT', default='3306'),
            'OPTIONS': {
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
                'charset': 'utf8mb4',
            },
        })
    else:
        _DB_CONFIG['NAME'] = BASE_DIR / config('DB_NAME', default='db.sqlite3')

    DATABASES = {'default': _DB_CONFIG}

# Custom User Model
AUTH_USER_MODEL = 'users.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '30/min',
        'user': '300/min',
        'login': '5/min',
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
}

# JWT Settings
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=config('JWT_ACCESS_TOKEN_LIFETIME', default=60, cast=int)),
    'REFRESH_TOKEN_LIFETIME': timedelta(minutes=config('JWT_REFRESH_TOKEN_LIFETIME', default=1440, cast=int)),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
}

# CORS settings - Allow mobile app connections
CORS_ALLOWED_ORIGINS = [
    "http://localhost:8083",
    "http://127.0.0.1:8083",
    "http://localhost:8081",  # Expo web dev server
    "http://127.0.0.1:8081",
    "http://127.0.0.1:9279",  # Browser preview proxy
]

# Allow all origins for mobile app API access (mobile uses JWT, not cookies)
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = False

# Session settings
SESSION_COOKIE_AGE = 7200  # 2 hours
SESSION_SAVE_EVERY_REQUEST = True

# Email settings (use console backend for dev, SMTP for production)
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='CMAM Tracker <noreply@nutri.pharn.org>')

# Authentication URLs
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

# Security settings
if not DEBUG:
    # Trust the X-Forwarded-Proto header set by reverse proxies (Railway,
    # Render, etc.) that terminate SSL and forward plain HTTP internally.
    # Without this, SECURE_SSL_REDIRECT causes an infinite redirect loop.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

# Logging - ensure logs directory exists
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': LOG_DIR / 'django.log',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

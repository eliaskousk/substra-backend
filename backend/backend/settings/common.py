"""
Django settings for backend project.

Generated by 'django-admin startproject' using Django 2.0.5.

For more information on this file, see
https://docs.djangoproject.com/en/2.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.0/ref/settings/
"""

import os
import sys
from datetime import timedelta

from libs.gen_secret_key import write_secret_key


TRUE_VALUES = {
    't', 'T',
    'y', 'Y', 'yes', 'YES',
    'true', 'True', 'TRUE',
    'on', 'On', 'ON',
    '1', 1,
    True
}


def to_bool(value):
    return value in TRUE_VALUES


# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

sys.path.append(PROJECT_ROOT)
sys.path.append(os.path.normpath(os.path.join(PROJECT_ROOT, 'libs')))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_FILE = os.path.normpath(os.path.join(PROJECT_ROOT, 'SECRET'))

# KEY CONFIGURATION
# Try to load the SECRET_KEY from our SECRET_FILE. If that fails, then generate
# a random SECRET_KEY and save it into our SECRET_FILE for future loading. If
# everything fails, then just raise an exception.
try:
    SECRET_KEY = open(SECRET_FILE).read().strip()
except IOError:
    try:
        SECRET_KEY = write_secret_key(SECRET_FILE)
    except IOError:
        raise Exception(f'Cannot open file `{SECRET_FILE}` for writing.')
# END KEY CONFIGURATION

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']

# Application definition

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'django_celery_results',
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_simplejwt.token_blacklist',
    'substrapp',
    'node',
    'users',
    'drf_spectacular',
]

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'node.authentication.NodeBackend',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.RemoteUserMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'libs.health_check_middleware.HealthCheckMiddleware',
]


DJANGO_LOG_SQL_QUERIES = to_bool(os.environ.get('DJANGO_LOG_SQL_QUERIES', 'True'))
if DJANGO_LOG_SQL_QUERIES:
    MIDDLEWARE.append(
        'libs.sql_printing_middleware.SQLPrintingMiddleware'
    )

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'backend.wsgi.application'

SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# Database
# https://docs.djangoproject.com/en/1.9/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(PROJECT_ROOT, 'db.sqlite3'),
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': '/tmp/django_cache',
    }
}

# Password validation
# https://docs.djangoproject.com/en/2.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'libs.zxcvbn_validator.ZxcvbnValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 9,
        }
    },
    {
        'NAME': 'libs.maximum_length_validator.MaximumLengthValidator',
        'OPTIONS': {
            'max_length': 64
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/2.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.0/howto/static-files/

STATIC_URL = '/static/'

MEDIA_ROOT = os.path.join(PROJECT_ROOT, 'medias')
MEDIA_URL = '/media/'

SITE_ID = 1

TASK = {
    'CAPTURE_LOGS': to_bool(os.environ.get('TASK_CAPTURE_LOGS', True)),
    'CLEAN_EXECUTION_ENVIRONMENT': to_bool(os.environ.get('TASK_CLEAN_EXECUTION_ENVIRONMENT', True)),
    'CACHE_DOCKER_IMAGES': to_bool(os.environ.get('TASK_CACHE_DOCKER_IMAGES', False)),
    'CHAINKEYS_ENABLED': to_bool(os.environ.get('TASK_CHAINKEYS_ENABLED', False)),
    'LIST_WORKSPACE': to_bool(os.environ.get('TASK_LIST_WORKSPACE', True)),
    'BUILD_IMAGE': to_bool(os.environ.get('BUILD_IMAGE', True)),
    'KANIKO_MIRROR': to_bool(os.environ.get('KANIKO_MIRROR', False)),
    'KANIKO_IMAGE': os.environ.get('KANIKO_IMAGE'),
    'COMPUTE_REGISTRY': os.environ.get('COMPUTE_REGISTRY'),
}

CELERY_ACCEPT_CONTENT = ['application/json']
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TASK_SERIALIZER = 'json'
CELERY_TASK_TRACK_STARTED = True  # since 4.0
CELERY_TASK_MAX_RETRIES = 5
CELERY_TASK_RETRY_DELAY_SECONDS = 2
CELERY_WORKER_CONCURRENCY = int(os.environ.get('CELERY_WORKER_CONCURRENCY', 1))
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'amqp://localhost:5672//'),

DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000

EXPIRY_TOKEN_LIFETIME = timedelta(minutes=int(os.environ.get('EXPIRY_TOKEN_LIFETIME', 24 * 60)))

GZIP_MODELS = to_bool(os.environ.get('GZIP_MODELS', False))

ENABLE_REMOVE_LOCAL_CP_FOLDERS = to_bool(os.environ.get('ENABLE_REMOVE_LOCAL_CP_FOLDERS', True))

HTTP_CLIENT_TIMEOUT_SECONDS = int(os.environ.get('HTTP_CLIENT_TIMEOUT_SECONDS', 30))

LOGGING_USE_COLORS = to_bool(os.environ.get('LOGGING_USE_COLORS', True))


# Without this import statement, hfc.fabric outputs DEBUG-level logs regardless of LOGGING configuration.
# Importing the module early ensures these steps happen in order:
# 1. hfc.fabric is imported and all the associated loggers are configured  (log level, handler, etc...)
# 2. Loggers are re-configured with the `LOGGING` statement, overriding the configuration from step 1
import hfc.fabric

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'class': 'libs.formatters.TaskFormatter',
            'format': '%(asctime)s - %(task_id)s - %(levelname)s - %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        # root logger
        '': {
            'level': 'WARNING',
            'handlers': ['console'],
            'propagate': True,
        },
        # django and its applications
        'django': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False,
        },
        'substrapp': {
            'level': 'DEBUG',
            'handlers': ['console'],
            'propagate': False,
        },
        'events': {
            'level': 'DEBUG',
            'handlers': ['console'],
            'propagate': False,
        },
        # third-party libraries
        'hfc': {
            'level': 'WARNING',
            'handlers': ['console'],
            'propagate': True,
        },
        'celery': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': True,
        },
    }
}

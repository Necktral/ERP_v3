from .base import *  # noqa

DEBUG = True
SYNC_DEMO_COMMANDS_ENABLED = True

from datetime import timedelta

# Dev: tolerante (evita lockouts molestos en desarrollo)
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=15)
AXES_COOLOFF_TIME = timedelta(seconds=env.int("AXES_COOLOFF_SECONDS", default=300))

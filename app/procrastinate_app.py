import os

from procrastinate import App, PsycopgConnector

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://codedelta:codedelta@localhost:5432/codedelta"
)

procrastinate_app = App(connector=PsycopgConnector(conninfo=DATABASE_URL))

# Importing tasks registers them on procrastinate_app; needed so the worker
# process (which only loads this module) knows about them.
from app import tasks  # noqa: E402,F401

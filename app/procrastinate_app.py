import os

from procrastinate import App, PsycopgConnector

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://codedelta:codedelta@localhost:5432/codedelta"
)

procrastinate_app = App(connector=PsycopgConnector(conninfo=DATABASE_URL))

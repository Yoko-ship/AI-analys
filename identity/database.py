"""PostgreSQL connection ownership for account services."""
from psycopg import connect
from psycopg.rows import dict_row
from identity import schema, settings


class IdentityDatabase:
    def __init__(self, database_url=None):
        self.database_url = (database_url or settings.DATABASE_URL).strip()
        if self.database_url:
            schema.initialize(self.connect)
        else:
            settings.logger.warning("DATABASE_URL is not configured; web auth is disabled")

    def connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for website authentication")
        connection = connect(self.database_url)
        connection.row_factory = dict_row
        return connection

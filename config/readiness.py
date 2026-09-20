"""Read-only readiness checks shared by the command and health endpoint."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def database_ready():
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        if cursor.fetchone() != (1,):
            return False
    executor = MigrationExecutor(connection)
    executor.loader.check_consistent_history(connection)
    return not executor.migration_plan(executor.loader.graph.leaf_nodes())

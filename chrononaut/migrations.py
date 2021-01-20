from alembic.operations import Operations, MigrateOperation
from chrononaut import ChrononautException


@Operations.register_operation("migrate_from_history_table")
class MigrateFromHistoryTableOp(MigrateOperation):
    """
    Migrate a single history table into the single activity model. Pass in base table
    name to migrate from (without the ``_history`` suffix).
    """

    def __init__(self, table_name, schema=None):
        self.schema = schema
        self.table_name = table_name

    @classmethod
    def migrate_from_history_table(cls, operations, table_name, **kwargs):
        op = MigrateFromHistoryTableOp(table_name, **kwargs)
        return operations.invoke(op)

    def reverse(self):
        return MigrateToHistoryTableOp(self.table_name, schema=self.schema)


@Operations.register_operation("migrate_to_history_table")
class MigrateToHistoryTableOp(MigrateOperation):
    """
    Migrate activity entries into a history table. Pass in base table name
    to migrate to (without the ``_history`` suffix).
    """

    def __init__(self, table_name, schema=None):
        self.schema = schema
        self.table_name = table_name

    @classmethod
    def migrate_to_history_table(cls, operations, table_name, **kwargs):
        op = MigrateToHistoryTableOp(table_name, **kwargs)
        return operations.invoke(op)

    def reverse(self):
        return MigrateFromHistoryTableOp(self.table_name, schema=self.schema)


@Operations.implementation_for(MigrateFromHistoryTableOp)
def migrate_from_history_table(operations, operation):
    activity_table = "activity" if not operation.schema else operation.schema + ".activity"
    table_name = (
        operation.table_name.replace("_history", "")
        if operation.table_name.endswith("_history")
        else operation.table_name
    )
    history_table = table_name + "_history"

    sql = (
        "INSERT INTO {}(table_name, changed, version, data, user_info, extra_info) "
        "SELECT '{}', changed, version, "
        "row_to_json({}.*)::jsonb #- '{{change_info}}' #- '{{changed}}', "
        "change_info #- '{{extra}}', coalesce(change_info->'extra', '{{}}')::jsonb "
        "FROM {} ORDER BY changed ASC"
    ).format(activity_table, table_name, history_table, history_table)

    conn = operations
    conn.execute(sql)


@Operations.implementation_for(MigrateToHistoryTableOp)
def migrate_to_history_table(operations, operation):
    raise ChrononautException("Migrating back to history tables is not supported")

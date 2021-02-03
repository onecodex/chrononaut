from alembic.operations import Operations, MigrateOperation
from alembic.autogenerate import renderers, comparators
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
    activity_table = (
        "chrononaut_activity" if not operation.schema else operation.schema + ".chrononaut_activity"
    )
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


@renderers.dispatch_for(MigrateFromHistoryTableOp)
def render_migrate_from_history_table(autogen_context, op):
    if op.schema:
        return "op.migrate_from_history_table('{}', '{}')".format(op.table_name, op.schema)
    else:
        return "op.migrate_from_history_table('{}')".format(op.table_name)


@renderers.dispatch_for(MigrateToHistoryTableOp)
def render_migrate_to_history_table(autogen_context, op):
    return ""  # empty by design


@comparators.dispatch_for("table")
def compare_dropped_table(
    autogen_context, modify_ops, schema, table_name, conn_table, metadata_table
):
    is_drop_table = metadata_table is None
    # TODO: try to narrow down this condition so that we don't capture a different table by accident
    if (
        not is_drop_table
        or not table_name.endswith("_history")
        or "version" not in conn_table._columns
    ):
        return
    if "chrononaut_activity" not in {t.name for t in autogen_context.sorted_tables}:
        raise ChrononautException("Cannot migrate if 'chrononaut_activity' table is not present")

    modify_ops.ops.append(MigrateFromHistoryTableOp(table_name, schema=schema))

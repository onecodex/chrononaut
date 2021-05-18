import alembic
from chrononaut import ChrononautException


@alembic.operations.Operations.register_operation("migrate_from_history_table")
class MigrateFromHistoryTableOp(alembic.operations.MigrateOperation):
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


@alembic.operations.Operations.register_operation("migrate_to_history_table")
class MigrateToHistoryTableOp(alembic.operations.MigrateOperation):
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


@alembic.operations.Operations.implementation_for(MigrateFromHistoryTableOp)
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

    ops = operations
    # Fetching primary key columns
    sql = """
        SELECT a.attname FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = '{}'::regclass AND i.indisprimary AND a.attname <> 'version'
    """.format(
        history_table
    )
    result = ops.impl._exec(sql)
    primary_keys = [r[0] for r in result.fetchall()]

    if not primary_keys:
        # TODO: warn about this case
        return

    history_pk_obj = ", ".join(["'{0}', {1}.{0}".format(pk, history_table) for pk in primary_keys])
    parent_pk_obj = ", ".join(["'{0}', {1}.{0}".format(pk, table_name) for pk in primary_keys])

    # Step 1: copy records from the history table converting to snapshot format
    sql = (
        """
        INSERT INTO {}(table_name, changed, version, key, data, user_info, extra_info)
        SELECT '{}', changed, version, json_build_object({}),
        row_to_json({}.*)::jsonb #- '{{change_info}}' #- '{{changed}}',
        change_info #- '{{extra}}', coalesce(change_info->'extra', '{{}}')::jsonb
        FROM {} ORDER BY changed ASC
        """
    ).format(activity_table, table_name, history_pk_obj, history_table, history_table)
    ops.execute(sql)

    # Step 2: copy the current state from the parent table converting to snapshot format
    sql = (
        """
        INSERT INTO {0}(table_name, changed, version, key, data, user_info, extra_info)
        SELECT '{1}', current_timestamp, version, json_build_object({2}),
        row_to_json({1}.*)::jsonb #- '{{change_info}}' #- '{{changed}}',
        '{{}}'::jsonb, '{{}}'::jsonb FROM {1}
        """
    ).format(activity_table, table_name, parent_pk_obj)
    ops.execute(sql)

    # Step 3: set `changed` timestamps and `change_info` to reflect snapshot creation
    sql = (
        """
        WITH lck AS (
            SELECT key, version, coalesce(
                lag(changed) over (partition by key order by version),
                changed
            ) AS new_changed,
            coalesce(
                lag(user_info) over (partition by key order by version),
                '{{}}'::jsonb
            ) AS new_user_info,
            coalesce(
                lag(extra_info) over (partition by key order by version),
                '{{}}'::jsonb
            ) AS new_extra_info
            FROM {0}
            WHERE table_name = '{1}'
        )
        UPDATE {0} SET changed = lck.new_changed,
            user_info = lck.new_user_info, extra_info = lck.new_extra_info
        FROM lck
        WHERE {0}.key = lck.key AND {0}.version = lck.version AND {0}.table_name = '{1}'
        """
    ).format(activity_table, table_name)
    ops.execute(sql)

    # Step 4: set the insert timestamp from `created_at` column if exists
    sql = """
        SELECT attname FROM pg_attribute
        WHERE attrelid = '{}'::regclass AND NOT attisdropped AND attname = 'created_at';
    """.format(
        table_name
    )

    result = ops.impl._exec(sql)
    created_at_result = [r[0] for r in result.fetchall()]

    if not created_at_result:
        return

    sql = """
    WITH lck AS (
        SELECT json_build_object({0})::jsonb as key, created_at FROM {1}
    )
    UPDATE {2} SET changed = lck.created_at
    FROM lck
    WHERE {2}.version = 0 AND {2}.table_name = '{1}' and {2}.key = lck.key
    """.format(
        parent_pk_obj, table_name, activity_table
    )
    ops.execute(sql)


@alembic.operations.Operations.implementation_for(MigrateToHistoryTableOp)
def migrate_to_history_table(operations, operation):
    raise ChrononautException("Migrating back to history tables is not supported")


@alembic.autogenerate.renderers.dispatch_for(MigrateFromHistoryTableOp)
def render_migrate_from_history_table(autogen_context, op):
    if op.schema:
        return "op.migrate_from_history_table('{}', '{}')".format(op.table_name, op.schema)
    else:
        return "op.migrate_from_history_table('{}')".format(op.table_name)


@alembic.autogenerate.renderers.dispatch_for(MigrateToHistoryTableOp)
def render_migrate_to_history_table(autogen_context, op):
    return ""  # empty by design


@alembic.autogenerate.comparators.dispatch_for("table")
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

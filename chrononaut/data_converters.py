from sqlalchemy.sql.expression import text
from chrononaut.versioned import Versioned
from chrononaut.exceptions import ChrononautException
import time


class HistoryModelDataConverter:
    def __init__(self, model, id_column="id"):
        if not issubclass(model, Versioned):
            raise ChrononautException("Cannot migrate data from non-Versioned model")

        self.last_converted_id = None

        self.model = model
        self.table_name = self.model.__tablename__
        self.id_column = id_column
        self.history_table_name = self.table_name + "_history"
        self.activity_table = self.model.metadata._activity_cls.__tablename__
        self.from_query_partial = "FROM {} ".format(self.table_name)
        self.history_from_query_partial = "FROM {} ".format(self.history_table_name)
        self.row_json_partial = "row_to_json({}.*)::jsonb ".format(self.table_name)
        self.history_row_json_partial = "row_to_json({}.*)::jsonb ".format(self.history_table_name)

        self.version_partial = None
        self.created_at_partial = None

        # Gathering primary keys
        pks = [
            self.model.__mapper__.get_property_by_column(k).key
            for k in self.model.__mapper__.primary_key
            if k.key != "version"
        ]
        self.history_pk_obj_partial = ", ".join(
            ["'{0}', {1}.{0}".format(key, self.history_table_name) for key in pks]
        )
        self.pk_obj_partial = ", ".join(
            ["'{0}', {1}.{0}".format(key, self.table_name) for key in pks]
        )

        join_table = self.table_name

        # Get columns (iterating mappers to root to handle concrete base class model)
        for mapper in self.model.__mapper__.iterate_to_root():
            mapper_table = mapper.local_table.name
            history_mapper_table = mapper_table + "_history"

            # Building query partials
            if mapper_table != self.table_name:
                self.from_query_partial += "JOIN {0} ON {1}.id = {0}.id ".format(
                    mapper_table, join_table
                )
                self.history_from_query_partial += (
                    "JOIN {0} ON {1}.id = {0}.id AND {1}.version = {0}.version ".format(
                        history_mapper_table, join_table + "_history"
                    )
                )
                self.row_json_partial += "|| row_to_json({}.*)::jsonb ".format(mapper_table)
                self.history_row_json_partial += "|| row_to_json({}.*)::jsonb ".format(
                    mapper_table + "_history"
                )

            join_table = mapper_table

            if not self.version_partial:
                has_version_col = any(
                    [obj_col.key == "version" for obj_col in mapper.local_table.c]
                )
                if has_version_col:
                    self.version_partial = "{}.version".format(mapper_table)

            if not self.created_at_partial:
                has_created_at_col = any(
                    [obj_col.key == "created_at" for obj_col in mapper.local_table.c]
                )
                if has_created_at_col:
                    self.created_at_partial = "{}.created_at".format(mapper_table)

        if not self.version_partial:
            raise ChrononautException("Missing `version` column in model")

    def convert(self, session, limit=10000):
        """
        Converts `limit` objects from legacy history table model to the single table model.
        Note that it doesn't correspond to `limit` records as each object may be represented
        by several records, depending on it's history.

        Converted objects have the timestamps updated to reflect the correct snapshot model
        structure. Before, the rows contained (current_timestamp, old_state) tuples. Now
        they'll contain (current_timestamp, current_state). For insert records we fill in timestamp
        based on the model's `created_at` column (if exists).

        Can be run multiple times. This allows for converting data in chunks, recommended usage
        is to run the method until it returns 0.

        Returns the number of converted objects.
        """

        # Get the latest converted record
        if not self.last_converted_id:
            query = text(
                "SELECT MAX((data->'{0}')::int) FROM {1} WHERE table_name = '{2}'".format(
                    self.id_column, self.activity_table, self.table_name
                )
            )
            result = session.execute(query).first()
            if result and result[0]:
                self.last_converted_id = result[0]
            else:
                self.last_converted_id = -1

        # Get upper id for this conversion run
        query = text(
            """
            WITH ids AS (
                (SELECT {0} AS id FROM {1} WHERE {0} > {3})
                UNION
                (SELECT {0} AS id FROM {2} WHERE {0} > {3})
                ORDER BY id ASC LIMIT {4}
            )
            SELECT MAX(id), COUNT(id) FROM ids
            """.format(
                self.id_column,
                self.table_name,
                self.history_table_name,
                self.last_converted_id,
                limit,
            )
        )
        result = session.execute(query).first()
        if not result or not result[0]:
            # No ids left to convert
            return 0
        id_upper_bound = result[0]
        converted_ids = result[1]

        # Copy records from the history table converting to snapshot format
        # adding the current state from the parent table converting to snapshot format
        # Seting `changed` timestamps and `change_info` to reflect snapshot creation
        query = text(
            (
                """
            INSERT INTO {0}(table_name, changed, version, key, data, user_info, extra_info)
            SELECT table_name,
                COALESCE(
                    LAG(changed) OVER (PARTITION BY key ORDER BY version),
                    MIN(changed) OVER (PARTITION BY key)
                ),
                version, key, data, user_info, extra_info
            FROM (
                (
                    SELECT {4}.{2}, '{1}' as table_name, {4}.changed,
                    COALESCE({4}.version, 0) AS version, jsonb_build_object({3}) as key,
                    {5} #- '{{change_info}}' #- '{{changed}}' as data,
                    COALESCE({4}.change_info #- '{{extra}}', '{{}}')::jsonb as user_info,
                    COALESCE({4}.change_info->'extra', '{{}}')::jsonb as extra_info {6}
                    WHERE {4}.{2} > {12} AND {4}.{2} <= {13}
                )
                UNION
                (
                    SELECT {1}.{2}, '{1}' as table_name, {11} as changed,
                    COALESCE({7}, 0) as version, jsonb_build_object({8}) as key,
                    {9} #- '{{change_info}}' #- '{{changed}}' as data, '{{}}'::jsonb as user_info,
                    '{{}}'::jsonb as extra_info {10} WHERE {1}.{2} > {12} AND {1}.{2} <= {13}
                )
                ORDER BY {2} ASC
            ) source
            """
            ).format(
                self.activity_table,
                self.table_name,
                self.id_column,
                self.history_pk_obj_partial,
                self.history_table_name,
                self.history_row_json_partial,
                self.history_from_query_partial,
                self.version_partial,
                self.pk_obj_partial,
                self.row_json_partial,
                self.from_query_partial,
                self.created_at_partial or "current_timestamp",
                self.last_converted_id,
                id_upper_bound,
            )
        )
        result = session.execute(query)
        session.commit()

        self.last_converted_id = id_upper_bound
        return converted_ids

    def convert_all(self, session):
        """
        Similar to `convert` method, but converts _all_ of the records from a given table.
        Due to not having to split up the data, it's faster than the `convert` counterpart.

        Warning: running multiple times will result in duplicated data, only use for smaller
        tables and run _once_ per table. If unsure, use the `convert` method.
        """

        # Copy records from the history table converting to snapshot format
        # adding the current state from the parent table converting to snapshot format
        # Seting `changed` timestamps and `change_info` to reflect snapshot creation
        query = text(
            (
                """
            INSERT INTO {0}(table_name, changed, version, key, data, user_info, extra_info)
            SELECT table_name,
                COALESCE(
                    LAG(changed) OVER (PARTITION BY key ORDER BY version),
                    MIN(changed) OVER (PARTITION BY key)
                ),
                version, key, data, user_info, extra_info
            FROM (
                (
                    SELECT {4}.{2}, '{1}' as table_name, {4}.changed,
                    COALESCE({4}.version, 0) AS version, jsonb_build_object({3}) as key,
                    {5} - 'change_info'::text - 'changed'::text as data,
                    COALESCE({4}.change_info - 'extra'::text, '{{}}')::jsonb as user_info,
                    COALESCE({4}.change_info->'extra', '{{}}')::jsonb as extra_info {6}
                )
                UNION
                (
                    SELECT {1}.{2}, '{1}' as table_name, {11} as changed,
                    COALESCE({7}, 0) as version, jsonb_build_object({8}) as key,
                    {9} - 'change_info'::text - 'changed'::text as data, '{{}}'::jsonb as user_info,
                    '{{}}'::jsonb as extra_info {10}
                )
                ORDER BY {2} ASC
            ) source
            """
            ).format(
                self.activity_table,
                self.table_name,
                self.id_column,
                self.history_pk_obj_partial,
                self.history_table_name,
                self.history_row_json_partial,
                self.history_from_query_partial,
                self.version_partial,
                self.pk_obj_partial,
                self.row_json_partial,
                self.from_query_partial,
                self.created_at_partial or "current_timestamp",
            )
        )
        session.execute(query)
        session.commit()

    def update(self, session, update_from=None):
        """
        Updates new objects from legacy history table model to the single table model.
        Finds new objects and changes made to existing objects and applies the diff to the
        single table history.
        If provided, `update_from` signifies point in time where the converter should begin
        looking for new or changed objects. Set it to the starting point of the conversion
        if performing multi-step conversion. If it's not set, this method tries to find the
        last change in the existing `chrononaut_activity` table or sets it to unix 0 if that
        fails.

        Use this script if converting large amounts of data while requiring minimal downtime.
        In this case, the scenario should be:
        1. Run a migration to create the `chrononaut_activity` table and its index.
        2. Run `convert` / `convert_all` operations on all your tables, mark down start timestamp.
        3. Initiate downtime.
        4. Run `update` on all your tables providing proper timestamp.
        5. Migrate your code to use the new model and resume functioning.

        This is the multi-step minimal-downtime approach. Can be run multiple times.

        Returns the number of converted objects.
        """

        # Get the last change
        query = text(
            "SELECT MAX(changed) FROM {0} WHERE table_name = '{1}'".format(
                self.activity_table, self.table_name
            )
        )
        if not update_from:
            result = session.execute(query).first()
            update_from = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(0))
            if result and result[0]:
                update_from = result[0]

        # Copy changed records from the history table converting to snapshot format
        # adding the current state from the parent table converting to snapshot format
        # Seting `changed` timestamps and `change_info` to reflect snapshot creation
        query = text(
            (
                """
            INSERT INTO {0}(table_name, changed, version, key, data, user_info, extra_info)
            SELECT update.table_name, update.changed, update.version, update.key, update.data,
                update.user_info, update.extra_info
            FROM (
                SELECT table_name,
                    LAG(changed) OVER (PARTITION BY key ORDER BY version) AS changed,
                    version, key, data, user_info, extra_info
                FROM (
                    (
                        SELECT {4}.{2}, '{1}' as table_name, {4}.changed,
                        COALESCE({4}.version, 0) AS version, jsonb_build_object({3}) as key,
                        {5} #- '{{change_info}}' #- '{{changed}}' as data,
                        COALESCE({4}.change_info #- '{{extra}}', '{{}}')::jsonb as user_info,
                        COALESCE({4}.change_info->'extra', '{{}}')::jsonb as extra_info {6}
                        WHERE {4}.changed > '{12}'
                    )
                    UNION
                    (
                        SELECT {1}.{2}, '{1}' as table_name, {11} as changed,
                        COALESCE({7}, 0) as version, jsonb_build_object({8}) as key,
                        {9} #- '{{change_info}}' #- '{{changed}}' as data,
                        '{{}}'::jsonb as user_info, '{{}}'::jsonb as extra_info {10}
                    )
                    ORDER BY {2} ASC
                ) source
            ) update
            WHERE update.changed IS NOT NULL
            """
            ).format(
                self.activity_table,
                self.table_name,
                self.id_column,
                self.history_pk_obj_partial,
                self.history_table_name,
                self.history_row_json_partial,
                self.history_from_query_partial,
                self.version_partial,
                self.pk_obj_partial,
                self.row_json_partial,
                self.from_query_partial,
                self.created_at_partial or "current_timestamp",
                update_from,
            )
        )
        result = session.execute(query)
        session.commit()

        # Append the new records
        res = 1
        while res > 0:
            res = self.convert(session)

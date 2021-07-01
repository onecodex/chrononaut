from sqlalchemy.sql.expression import text
from chrononaut.versioned import Versioned
from chrononaut.exceptions import ChrononautException
import logging


class HistoryModelDataConverter:
    def __init__(self, model):
        if not issubclass(model, Versioned):
            raise ChrononautException("Cannot migrate data from non-Versioned model")

        self.last_converted_id = None

        self.model = model
        self.table_name = self.model.__tablename__
        self.history_table_name = self.table_name + "_history"
        self.activity_table = self.model.metadata._activity_cls.__tablename__
        self.from_query_partial = "FROM {} ".format(self.table_name)
        self.history_from_query_partial = "FROM {} ".format(self.history_table_name)
        self.row_json_partial = "row_to_json({}.*)::jsonb ".format(self.table_name)
        self.history_row_json_partial = "row_to_json({}.*)::jsonb ".format(self.history_table_name)

        self.version_partial = ""
        self.created_at_partial = ""

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
                "SELECT MAX((data->'id')::int) FROM {0} WHERE table_name = '{1}'".format(
                    self.activity_table, self.table_name
                )
            )
            logging.info(f"Executing {query}")
            result = session.execute(query).first()
            if result and result[0]:
                self.last_converted_id = result[0]
            else:
                self.last_converted_id = -1

        # Get upper id for this conversion run
        query = text(
            """
            WITH ids AS (
                (SELECT id FROM {0} WHERE id > {2})
                UNION
                (SELECT id FROM {1} WHERE id > {2})
                ORDER BY id ASC LIMIT {3}
            )
            SELECT MAX(id), COUNT(id) FROM ids
            """.format(
                self.table_name, self.history_table_name, self.last_converted_id, limit
            )
        )
        logging.info(f"Executing {query}")
        result = session.execute(query).first()
        if not result or not result[0]:
            # No ids left to convert
            return 0
        id_upper_bound = result[0]
        converted_ids = result[1]

        # Copy records from the history table converting to snapshot format
        # adding the current state from the parent table converting to snapshot format
        query = text(
            (
                """
            INSERT INTO {0}(table_name, changed, version, key, data, user_info, extra_info)
            SELECT table_name, changed, version, key, data, user_info, extra_info
            FROM (
                (
                    SELECT {3}.id, '{1}' as table_name, {3}.changed,
                    COALESCE({3}.version, 0) AS version, json_build_object({2})::jsonb as key,
                    {4} #- '{{change_info}}' #- '{{changed}}' as data,
                    {3}.change_info #- '{{extra}}' as user_info,
                    COALESCE({3}.change_info->'extra', '{{}}')::jsonb as extra_info {5}
                    WHERE {3}.id > {10} AND {3}.id <= {11}
                )
                UNION
                (
                    SELECT {1}.id, '{1}' as table_name, current_timestamp as changed,
                    COALESCE({6}, 0) as version, json_build_object({7})::jsonb as key,
                    {8} #- '{{change_info}}' #- '{{changed}}' as data, '{{}}'::jsonb as user_info,
                    '{{}}'::jsonb as extra_info {9} WHERE {1}.id > {10} AND {1}.id <= {11}
                )
                ORDER BY id ASC
            ) source
            """
            ).format(
                self.activity_table,
                self.table_name,
                self.history_pk_obj_partial,
                self.history_table_name,
                self.history_row_json_partial,
                self.history_from_query_partial,
                self.version_partial,
                self.pk_obj_partial,
                self.row_json_partial,
                self.from_query_partial,
                self.last_converted_id,
                id_upper_bound,
            )
        )
        logging.info(f"Executing {query}")
        result = session.execute(query)
        session.commit()

        # Set `changed` timestamps and `change_info` to reflect snapshot creation
        query = text(
            (
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
                WHERE table_name = '{1}' AND (data->'id')::int > {2} AND (data->'id')::int <= {3}
            )
            UPDATE {0} SET changed = lck.new_changed,
                user_info = lck.new_user_info, extra_info = lck.new_extra_info
            FROM lck
            WHERE {0}.key = lck.key AND {0}.version = lck.version AND {0}.table_name = '{1}'
            """
            ).format(self.activity_table, self.table_name, self.last_converted_id, id_upper_bound)
        )
        logging.info(f"Executing {query}")
        session.execute(query)
        session.commit()

        # Set the insert timestamp from `created_at` column if exists
        if self.created_at_partial:
            query = text(
                """
                WITH lck AS (
                    SELECT json_build_object({0})::jsonb as key, {3} AS created_at {4}
                    WHERE {1}.id > {5} AND {1}.id <= {6}
                )
                UPDATE {2} SET changed = lck.created_at
                FROM lck
                WHERE {2}.version = 0 AND {2}.table_name = '{1}' and {2}.key = lck.key
            """.format(
                    self.pk_obj_partial,
                    self.table_name,
                    self.activity_table,
                    self.created_at_partial,
                    self.from_query_partial,
                    self.last_converted_id,
                    id_upper_bound,
                )
            )
            logging.info(f"Executing {query}")
            session.execute(query)
            session.commit()

        self.last_converted_id = id_upper_bound
        return converted_ids

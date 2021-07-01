from sqlalchemy.sql.expression import text
from chrononaut.versioned import Versioned
from chrononaut.exceptions import ChrononautException
import logging


class HistoryModelDataConverter:
    def __init__(self, model):
        if not issubclass(model, Versioned):
            raise ChrononautException("Cannot migrate data from non-Versioned model")

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
        Converts `limit` records from legacy history table model to the single table model.
        Can be run multiple times. This allows for converting data in chunks, recommended usage
        is to run the method until it returns 0.

        Returns the number of converted records.
        """

        limit_left = limit

        # 1. Copy records from the history table converting to snapshot format
        query = text(
            (
                """
            WITH existing AS (SELECT key, version FROM {0} WHERE table_name = '{1}')
            INSERT INTO {0}(table_name, changed, version, key, data, user_info, extra_info)
            SELECT '{1}', {3}.changed, COALESCE({3}.version, 0) AS version,
            json_build_object({2}), {4} #- '{{change_info}}' #- '{{changed}}',
            {3}.change_info #- '{{extra}}', coalesce({3}.change_info->'extra', '{{}}')::jsonb {5}
            WHERE NOT EXISTS (SELECT 1 FROM existing ex
            WHERE ex.key = json_build_object({2})::jsonb AND ex.version = {3}.version)
            ORDER BY {3}.changed ASC LIMIT {6}
            """
            ).format(
                self.activity_table,
                self.table_name,
                self.history_pk_obj_partial,
                self.history_table_name,
                self.history_row_json_partial,
                self.history_from_query_partial,
                limit_left,
            )
        )
        logging.info(f"Executing {query}")
        result = session.execute(query)
        session.commit()
        limit_left -= result.rowcount

        # Return if we already used up the limit
        if limit_left <= 0:
            return limit - limit_left

        # 2. Copy the current state from the parent table converting to snapshot format
        query = text(
            (
                """
            WITH existing AS (SELECT key, version FROM {0} WHERE table_name = '{1}')
            INSERT INTO {0}(table_name, changed, version, key, data, user_info, extra_info)
            SELECT '{1}', current_timestamp, COALESCE({2}, 0) as version,
            json_build_object({3}), {4} #- '{{change_info}}' #- '{{changed}}',
            '{{}}'::jsonb, '{{}}'::jsonb {5}
            WHERE NOT EXISTS (SELECT 1 FROM existing ex
            WHERE ex.key = json_build_object({3})::jsonb AND ex.version = {2})
            ORDER BY {1}.id ASC LIMIT {6}
            """
            ).format(
                self.activity_table,
                self.table_name,
                self.version_partial,
                self.pk_obj_partial,
                self.row_json_partial,
                self.from_query_partial,
                limit_left,
            )
        )
        logging.info(f"Executing {query}")
        result = session.execute(query)
        session.commit()
        limit_left -= result.rowcount
        return limit - limit_left

    def update_timestamps(self, session):
        """
        Updates the timestamps to reflect the correct snapshot model structure. Before,
        the rows contained (current_timestamp, old_state) tuples. Now they'll contain
        (current_timestamp, current_state). For insert records we fill in timestamp based
        on the model's `created_at` column (if exists).
        """

        # 3. Set `changed` timestamps and `change_info` to reflect snapshot creation
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
                WHERE table_name = '{1}'
            )
            UPDATE {0} SET changed = lck.new_changed,
                user_info = lck.new_user_info, extra_info = lck.new_extra_info
            FROM lck
            WHERE {0}.key = lck.key AND {0}.version = lck.version AND {0}.table_name = '{1}'
            """
            ).format(self.activity_table, self.table_name)
        )
        logging.info(f"Executing {query}")
        session.execute(query)
        session.commit()

        # 4. Set the insert timestamp from `created_at` column if exists
        if self.created_at_partial:
            query = text(
                """
                WITH lck AS (
                    SELECT json_build_object({0})::jsonb as key, {3} AS created_at {4}
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
                )
            )
            logging.info(f"Executing {query}")
            session.execute(query)
            session.commit()

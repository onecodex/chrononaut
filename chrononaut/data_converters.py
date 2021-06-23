from sqlalchemy.sql.expression import text
from chrononaut.versioned import Versioned
from chrononaut.exceptions import ChrononautException


class HistoryModelDataConverter:
    def __init__(self, model):
        self.model = model

    def convert(self, session, limit=10000):
        """
        Converts `limit` records from legacy history table model to the single table model.
        Can be run multiple times. This allows for converting data in chunks, recommended usage
        is to run the method until it returns 0.

        Returns the number of converted records.
        """
        if not issubclass(self.model, Versioned):
            raise ChrononautException("Cannot migrate data from non-Versioned model")

        limit_left = limit

        table_name = self.model.__tablename__
        history_table_name = table_name + "_history"
        activity_table = self.model.metadata._activity_cls.__tablename__

        from_query_partial = "FROM {} ".format(table_name)
        history_from_query_partial = "FROM {} ".format(history_table_name)
        row_json_partial = "row_to_json({}.*)::jsonb ".format(table_name)
        history_row_json_partial = "row_to_json({}.*)::jsonb ".format(history_table_name)

        version_partial = ""
        created_at_partial = ""

        # Gathering primary keys
        pks = [
            self.model.__mapper__.get_property_by_column(k).key
            for k in self.model.__mapper__.primary_key
            if k.key != "version"
        ]
        history_pk_obj_partial = ", ".join(
            ["'{0}', {1}.{0}".format(key, history_table_name) for key in pks]
        )
        pk_obj_partial = ", ".join(["'{0}', {1}.{0}".format(key, table_name) for key in pks])

        join_table = table_name

        # Get columns (iterating mappers to root to handle concrete base class model)
        for mapper in self.model.__mapper__.iterate_to_root():
            mapper_table = mapper.local_table.name
            history_mapper_table = mapper_table + "_history"

            # Building query partials
            if mapper_table != table_name:
                from_query_partial += "JOIN {0} ON {1}.id = {0}.id ".format(
                    mapper_table, join_table
                )
                history_from_query_partial += (
                    "JOIN {0} ON {1}.id = {0}.id AND {1}.version = {0}.version ".format(
                        history_mapper_table, join_table + "_history"
                    )
                )
                row_json_partial += "|| row_to_json({}.*)::jsonb ".format(mapper_table)
                history_row_json_partial += "|| row_to_json({}.*)::jsonb ".format(
                    mapper_table + "_history"
                )

            join_table = mapper_table

            if not version_partial:
                has_version_col = any(
                    [obj_col.key == "version" for obj_col in mapper.local_table.c]
                )
                if has_version_col:
                    version_partial = "{}.version".format(mapper_table)

            if not created_at_partial:
                has_created_at_col = any(
                    [obj_col.key == "created_at" for obj_col in mapper.local_table.c]
                )
                if has_created_at_col:
                    created_at_partial = "{}.created_at".format(mapper_table)

        if not version_partial:
            raise ChrononautException("Missing `version` column in model")

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
                activity_table,
                table_name,
                history_pk_obj_partial,
                history_table_name,
                history_row_json_partial,
                history_from_query_partial,
                limit_left,
            )
        )
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
                activity_table,
                table_name,
                version_partial,
                pk_obj_partial,
                row_json_partial,
                from_query_partial,
                limit_left,
            )
        )
        result = session.execute(query)
        session.commit()
        limit_left -= result.rowcount

        # Return if we already used up the limit *or* if we didn't update anything
        if limit_left <= 0 or limit_left == limit:
            return limit - limit_left

        # The following steps need to be run in one go as it's too complicated to break them up

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
            ).format(activity_table, table_name)
        )
        session.execute(query)
        session.commit()

        # 4. Set the insert timestamp from `created_at` column if exists
        if created_at_partial:
            query = text(
                """
                WITH lck AS (
                    SELECT json_build_object({0})::jsonb as key, {3} AS created_at {4}
                )
                UPDATE {2} SET changed = lck.created_at
                FROM lck
                WHERE {2}.version = 0 AND {2}.table_name = '{1}' and {2}.key = lck.key
            """.format(
                    pk_obj_partial,
                    table_name,
                    activity_table,
                    created_at_partial,
                    from_query_partial,
                )
            )
            session.execute(query)
            session.commit()

        return limit - limit_left

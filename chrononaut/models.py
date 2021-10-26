import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from chrononaut.exceptions import UntrackedAttributeError, HiddenAttributeError, ChrononautException


def activity_factory(Base, schema=None):
    class ActivityBase(Base):
        __table_args__ = {"schema": schema}
        __tablename__ = "chrononaut_activity"
        __chrononaut_version__ = {}

        id = sa.Column(sa.BigInteger, primary_key=True)
        table_name = sa.Column(sa.Text, nullable=False)
        changed = sa.Column(sa.DateTime(timezone=True), nullable=False)
        version = sa.Column(sa.Integer, nullable=False, default=0)
        key = sa.Column(JSONB, server_default="{}", nullable=False)
        data = sa.Column(JSONB, server_default="{}", nullable=False)
        user_info = sa.Column(JSONB, server_default="{}", nullable=False)
        extra_info = sa.Column(JSONB, server_default="{}", nullable=False)

        # Ensuring quick access to the relevant records
        __extra_table_args__ = (sa.Index("ix_chrononaut_activity_key_table_name", key, table_name),)

    return ActivityBase


class HistorySnapshot(object):
    __initialized__ = False
    __eq_attrs__ = {"_key", "_data", "_untracked", "_hidden", "chrononaut_meta"}

    def __init__(self, activity_obj, untracked=None, hidden=None):
        self._key = activity_obj.key
        self._data = activity_obj.data
        self._version = activity_obj.version
        self.chrononaut_meta = {
            "table_name": activity_obj.table_name,
            "changed": activity_obj.changed,
            "user_info": activity_obj.user_info,
            "extra_info": activity_obj.extra_info,
        }
        self._untracked = untracked if untracked else []
        self._hidden = hidden if hidden else []
        self._activity_obj = activity_obj
        self.__initialized__ = True

    def diff(self, other_history_model):
        diff = {}
        hidden_cols = self._hidden

        if not other_history_model:
            return {k: (self._data[k], None) for k in self._data.keys() if k not in hidden_cols}
        elif self._version == other_history_model._version:
            # Exit early if we are comparing the same version
            return {}
        else:
            from_dict = self._data
            to_dict = other_history_model._data

            all_keys = set(from_dict.keys())
            all_keys.update(to_dict.keys())
            all_keys = all_keys.difference(hidden_cols)

            diff = {}
            for k in all_keys:
                if k in from_dict and k not in to_dict:
                    diff[k] = (from_dict[k], None)
                elif k not in from_dict and k in to_dict:
                    diff[k] = (None, to_dict[k])
                else:
                    # it's in both
                    if from_dict[k] != to_dict[k]:
                        diff[k] = (from_dict[k], to_dict[k])
        return diff

    def __getattr__(self, name):
        if name == "chrononaut_meta":
            return self.chrononaut_meta
        elif name in self._untracked:
            raise UntrackedAttributeError(
                "{} is explicitly untracked via __chrononaut_untracked__.".format(name)
            )
        elif name in self._hidden:
            raise HiddenAttributeError(
                "{} is explicitly hidden via __chrononaut_hidden__.".format(name)
            )
        elif name not in self._data:
            raise AttributeError("{} has no attribute `{}`".format(self, name))
        else:
            return self._data[name]

    def __setattr__(self, name, value):
        if self.__initialized__:
            raise ChrononautException("Cannot modify a HistorySnapshot model.")
        else:
            object.__setattr__(self, name, value)

    def __delattr__(self, name):
        raise ChrononautException("Cannot modify a HistorySnapshot model.")

    def __eq__(self, other):
        if isinstance(other, HistorySnapshot):
            return all(getattr(self, attr) == getattr(other, attr) for attr in self.__eq_attrs__)
        return False

    def __str__(self):
        return "{} at {}: {}".format(
            self.chrononaut_meta["table_name"], self.chrononaut_meta["changed"], self._data
        )

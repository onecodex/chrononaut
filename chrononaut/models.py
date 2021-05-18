import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from chrononaut.exceptions import UntrackedAttributeError, HiddenAttributeError, ChrononautException


def activity_factory(Base, schema=None):
    class ActivityBase(Base):
        __table_args__ = {"schema": schema}
        __tablename__ = "chrononaut_activity"

        id = sa.Column(sa.BigInteger, primary_key=True)
        table_name = sa.Column(sa.Text, nullable=False)
        changed = sa.Column(sa.DateTime(timezone=True), nullable=False)
        version = sa.Column(sa.Integer, nullable=False, default=0)
        key = sa.Column(JSONB, server_default="{}", nullable=False)
        data = sa.Column(JSONB, server_default="{}", nullable=False)
        user_info = sa.Column(JSONB, server_default="{}", nullable=False)
        extra_info = sa.Column(JSONB, server_default="{}", nullable=False)

        # Since we only ever do equality comparison, Hash Index is the best bet
        __extra_table_args__ = (
            sa.Index("ix_chrononaut_activity_key", key, postgresql_using="hash"),
            sa.Index("ix_chrononaut_activity_table_name", table_name, postgresql_using="hash"),
        )

    return ActivityBase


class HistorySnapshot(object):
    __initialized__ = False
    __eq_attrs__ = {"_key", "_data", "_untracked", "_hidden", "chrononaut_meta"}

    def __init__(
        self, key, data, table_name, changed, user_info, extra_info, untracked=None, hidden=None
    ):
        self._key = key
        self._data = data
        self.chrononaut_meta = {
            "table_name": table_name,
            "changed": changed,
            "user_info": user_info,
            "extra_info": extra_info,
        }
        self._untracked = untracked if untracked else []
        self._hidden = hidden if hidden else []
        self.__initialized__ = True

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

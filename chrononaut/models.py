import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from chrononaut.exceptions import UntrackedAttributeError, HiddenAttributeError, ChrononautException


def activity_factory(Base, schema=None):
    class ActivityBase(Base):
        __table_args__ = {"schema": schema}
        __tablename__ = "activity"

        id = sa.Column(sa.BigInteger, primary_key=True)
        table_name = sa.Column(sa.Text, nullable=False, index=True)
        changed = sa.Column(sa.DateTime(timezone=True), nullable=False)
        version = sa.Column(sa.Integer, nullable=False, default=0)
        data = sa.Column(JSONB, server_default="{}", nullable=False)
        user_info = sa.Column(JSONB, server_default="{}", nullable=False)
        extra_info = sa.Column(JSONB, server_default="{}", nullable=False)

    return ActivityBase


class HistorySnapshot(object):
    __initialized__ = False

    def __init__(self, data, table_name, changed, user_info, extra_info, untracked=[], hidden=[]):
        self.data = data
        self.table_name = table_name
        self.changed = changed
        self.user_info = user_info
        self.extra_info = extra_info
        self.untracked = untracked
        self.hidden = hidden
        self.__initialized__ = True

    def __getattr__(self, name):
        if name in self.untracked:
            raise UntrackedAttributeError(
                f"{name} is explicitly untracked via __chrononaut_untracked__."
            )
        elif name in self.hidden:
            raise HiddenAttributeError(f"{name} is explicitly hidden via __chrononaut_hidden__.")
        elif name not in self.data:
            raise AttributeError(f"{self} has no attribute {name}")
        else:
            return self.data[name]

    def __setattr__(self, name, value):
        if self.__initialized__:
            raise ChrononautException("Cannot modify a HistorySnapshot model.")
        else:
            object.__setattr__(self, name, value)

    def __delattr__(self, name):
        raise ChrononautException("Cannot modify a HistorySnapshot model.")

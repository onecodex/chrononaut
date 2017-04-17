"""Custom Exceptions raised by History Models
"""


class UntrackedAttributeError(AttributeError):
    pass


class HiddenAttributeError(AttributeError):
    pass

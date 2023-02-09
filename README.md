# chrononaut

![test](https://github.com/onecodex/chrononaut/workflows/test/badge.svg) [![codecov](https://codecov.io/gh/onecodex/chrononaut/branch/master/graph/badge.svg)](https://codecov.io/gh/onecodex/chrononaut) ![pre-commit](https://github.com/onecodex/chrononaut/workflows/pre-commit/badge.svg) ![Black Code Style](https://camo.githubusercontent.com/28a51fe3a2c05048d8ca8ecd039d6b1619037326/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f636f64652532307374796c652d626c61636b2d3030303030302e737667) [![Documentation Status](https://readthedocs.org/projects/chrononaut/badge/?version=latest)](http://chrononaut.readthedocs.io/en/latest/?badge=latest)

A history mixin with audit logging, record locking, and time travel (!) for PostgreSQL and Flask-SQLAlchemy. Requires Flask-SQLAlchemy >= 2.2. See [the documentation](https://chrononaut.readthedocs.io/) for more details. Development and all PRs should pass tests and linting on Github Actions, including use of [`pre-commit`](https://pre-commit.com) for automated linting with `flake8` and `black`.

## Using with `rationale`
Sometimes you may wish to additionally store a rationale for making a certain change; for these circumstances, you can make use of the `rationale` feature. Example usage:


```
with chrononaut.rationale("reasons"):
    sample.product = <product>
    db.session.commit()
```
If this is done, your rationale will be saved under `<version>.chrononaut_meta['extra_info']['rationale']` in the version object.

*Note* `db.session.commit()` must be included within the `with` scope, otherwise the `rationale` will not be properly saved.

## Migrating from 0.2 to 0.3
If using Alembic, database schema migration will be detected automatically.
In other cases please look at the table located in `activity_factory` function in `models.py` file.
Note that you should keep the old `*_history` tables if you with to migrate the data as well.

In order to migrate data from the old model, use the `HistoryModelDataConverter` model.
Example uses:
```python
from chrononaut.data_converters import HistoryModelDataConverter

# convert all records from a versioned `User` model with a non-standard `uuid` id column:
converter = HistoryModelDataConverter(User, id_column="uuid")
converter.convert_all(db.session)

# convert all records from a versioned `Transfer` model in a "chunked" mode (useful e.g. if
# a table has millions of rows which slow down a query)
converter = HistoryModelDataConverter(Transfer)
res = 1
while res > 0:
    res = converter.convert(db.session)

# convert data that may have been inserted in the old model after the initial conversion
# (e.g. if migrating a live system)
converter = HistoryModelDataConverter(Transfer)
converter.update(db.session, update_from="timestamp-of-initial-conversion")
```

> _Note: Future plans include extending supporting for SQLAlchemy more generally and across multiple databases._

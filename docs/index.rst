.. currentmodule:: chrononaut

Chrononaut
==========

`Chrononaut`_ is a simple package to provide versioning, change tracking, and record
locking for applications using `Flask-SQLAlchemy`_. It currently supports Postgres as
a database backend.

.. _Chrononaut: https://github.com/onecodex/chrononaut
.. _Flask-SQLAlchemy: http://flask-sqlalchemy.pocoo.org/2.1/

Getting started
---------------

Getting started with Chrononaut is a simple two step process. First, replace your :class:`FlaskSQLAlchemy`
database object with a Chrononaut :class:`VersionedSQLAlchemy` database connection::


    from flask_sqlalchemy import SQLAlchemy
    from chrononaut import VersionedSQLAlchemy

    # A standard, FlaskSQLAlchemy database connection without support
    # for automatic version tracking
    db = SQLAlchemy(app)

    # A Chrononaut database connection with automated versioning
    # for any models with a `Versioned` mixin
    db = VersionedSQLAlchemy(app)


This creates an ``chrononaut_activity`` table that keeps value snapshots for updated ``Versioned``
models, along with additional JSON ``user_info``, ``extra_info`` and ``changed`` columns explained
in more detail below.

After that, simply add the :class:`Versioned` mixin object to your standard Flask-SQLAlchemy models::

    # A simple User model with versioning to support tracking of, e.g.,
    # email and name changes.
    class User(db.Model, Versioned):
        __tablename__ = 'appuser'
        __chrononaut_untracked__ = ['login_count']
        __chrononaut_hidden__ = ['password']

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(80), unique=False)
        email = db.Column(db.String(255), unique=True)
        password = db.Column(db.Text())
        ...
        login_count = db.Column(db.Integer())


This creates starts tracking changes to the ``User`` model and populates the ``chrononaut_activity``
table with snapshots of previous values.


Using model history
-------------------
Chrononaut automatically generates history records for each model into which you mixin :class:`Versioned`. You can access past versions like so::

    # See if the user has changed their email
    # since they first signed up
    user = User.query.first()
    original_user_info = user.versions()[0]
    if user.email == original_user_info.email:
        print('User email matches!')
    else:
        print('The user has updated their email!')


Trying to access fields that are untracked or hidden raises an exception::

    print(original_user_info.password)     # Raises a HiddenAttributeError
    print(original_user_info.login_count)  # Raises an UntrackedAttributeError

For more information on fetching specific version records see :meth:`Versioned.versions`.

Fine-grained versioning
-----------------------
By default, Chrononaut will automatically version every column in a model.

In the above example, we do not want to retain past user passwords in our history table, so we add ``password`` to the model's ``__chrononaut_hidden__`` property. Changes to a user's password will now result in a new model version and creation of a history record, but the automatically generated snapshot record will not contain a ``password`` field and will only note that a hidden column was changed in its ``extra_info`` JSON column.

Similarly, Chrononaut's ``__chrononaut_untracked__`` property allows us to specify that we do not want to track a field at all. This is useful for changes that are regularly incremented, toggled, or otherwise changed but do not need to be tracked. A good example would be a ``starred`` property on an object or other UI state that might be persisted to the database between application sessions.


Migrations
----------
Chrononaut automatically generates a single SQLAlchemy model (and corresponding table) for tracking
each model with :class:`Versioned` mixin. This table is named ``chrononaut_activity``.
We recommend using `Alembic`_ for migrating your database.

.. _Alembic: http://alembic.zzzcomputing.com/en/latest/


Migrating from 0.1
------------------
If you have used Chrononaut 0.1 before, in order to migrate your project to 0.2, all the ``*_history`` tables need
to be migrated into the single ``chrononaut_activity`` table. We recommend using `Alembic` for this purpose. After
updating the Chrononaut version and generating a new migration, you'll notice that the ``chrononaut_activity`` table
was added and all the ```_history`` tables are being dropped.

If you want to convert your historic data, there is a ``chrononaut.data_converters.HistoryModelDataConverter`` class
which you can use to convert all the required models. The conversion script may be run multiple times - and it's the
recommended approach, run the script until it returns 0 (records converted) for each data model tyou want to convert.

We recommend migrating to the new version of Chrononaut in three steps:
* generate the migration to create the new ``chrononaut_activity`` table and indexes while removing drop table operations for ``*_history`` tables,
* convert the data in whatever way that's convenient,
* drop the ``*_history`` tables, e.g. by generating another migration.

.. warning:: Migrating the history data is non-reversible. Double check the generated Alembic migration script and migrate your data, otherwise it may be lost!


Suppressing versioning
----------------------
You may disable tracing version info for selected operations by using ``suppress_versioning`` context block::

    from chrononaut.unsafe import suppress_versioning

    with suppress_versioning():
        obj.modify()
        session.commit()

This will prevent tracing all insert, update and delete operations performed within this block. If needed, you
may also remove select history records by passing in a flag to the context block, e.g. to remove an object along
with all its history info::

    from chrononaut.unsafe import suppress_versioning

    with suppress_versioning(allow_deleting_history=True):
        for version in obj.versions():
            session.delete(version)
        session.delete(obj)
        session.commit()

Those operations will lead to loss of information and may lead to inconsistent database state, so don't use them.
If really needed, excercise extreme caution.


Known issues
------------
Adding a column to an already existing Primary Key on a table will make the historic versions of an object
from before the change inaccessible via the ``Versioned`` mixin methods. The historic records will still be
present in the database, but the ``versions``, ``version_at``, ``has_changed_since``, ``previous_version``
and ``diff`` methods will no longer see the versions before PK change. This is considered an extremely
rare scenario and won't be handled in the foreseeable future.

When handling polymorphic models implemented via concrete base table model, data for each subclass needs
to be converted separately. Migrating just the base class model won't work. Accessing the model's history
also only works for subclasses, base class model doesn't "see" its previous versions.


More details
------------
More in-depth information on Chrononaut's API is available below:

.. toctree::
   :maxdepth: 2

   basics

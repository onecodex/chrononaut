# chrononaut

![test](https://github.com/onecodex/chrononaut/workflows/test/badge.svg) [![codecov](https://codecov.io/gh/onecodex/chrononaut/branch/master/graph/badge.svg)](https://codecov.io/gh/onecodex/chrononaut) ![pre-commit](https://github.com/onecodex/chrononaut/workflows/pre-commit/badge.svg) ![Black Code Style](https://camo.githubusercontent.com/28a51fe3a2c05048d8ca8ecd039d6b1619037326/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f636f64652532307374796c652d626c61636b2d3030303030302e737667) [![Documentation Status](https://readthedocs.org/projects/chrononaut/badge/?version=latest)](http://chrononaut.readthedocs.io/en/latest/?badge=latest)

A history mixin with audit logging, record locking, and time travel (!) for PostgreSQL and Flask-SQLAlchemy. Requires Flask-SQLAlchemy >= 2.2. See [the documentation](https://chrononaut.readthedocs.io/) for more details. Development and all PRs should pass tests and linting on CircleCI, including use of [`pre-commit`](https://pre-commit.com) for automated linting with `flake8` and `black`.

> _Note: Future plans include extending supporting for SQLAlchemy more generally and across multiple databases._

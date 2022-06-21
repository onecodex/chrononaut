#!/usr/bin/env python
"""
``chrononaut``
------------

``chrononaut`` is a simple history mixin for SQLAlchemy models,
adding support for audit logging, record locking, and time travel!
"""
from setuptools import setup, find_packages
import sys

__version__ = "0.3.1"


if sys.version_info[0] < 3:
    sys.stderr.write("Requires Python 3 or up\n")
    sys.exit(1)


setup(
    name="chrononaut",
    version=__version__,  # noqa
    packages=find_packages(exclude=["*test*"]),
    install_requires=[
        "Flask>=2.1.0",
        "Flask-SQLAlchemy>=2.5.1",
        "SQLAlchemy>=1.4.0",
        "psycopg2>=2.7.1",
    ],
    extras_require={"user_info": ["Flask-Login>=0.4.0"]},
    include_package_data=True,
    zip_safe=False,
    dependency_links=[],
    author="Nick Greenfield",
    author_email="opensource@onecodex.com",
    long_description=__doc__,
    long_description_content_type="text/markdown",
    license="MIT License",
    keywords="Chrononaut",
    url="https://github.com/onecodex/chrononaut",
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Internet :: WWW/HTTP",
        "Framework :: Flask",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    test_suite="tests",
    setup_requires=["pytest-runner"],
    tests_require=["pytest", "Flask-Security-Fork"],
)

#!/usr/bin/env python
"""
``chrononaut``
------------

``chrononaut`` is a simple history mixin for SQLAlchemy models,
adding support for audit logging, record locking, and time travel!
"""
from setuptools import setup, find_packages

__version__ = "0.2.4"


setup(
    name="chrononaut",
    version=__version__,  # noqa
    packages=find_packages(exclude=["*test*"]),
    install_requires=["Flask>=0.12", "Flask-SQLAlchemy>=2.2", "pytz>=2017.2", "psycopg2>=2.7.1"],
    extras_require={"user_info": ["Flask-Login>=0.4.0"]},
    include_package_data=True,
    zip_safe=False,
    dependency_links=[],
    author="Nick Greenfield",
    author_email="opensource@onecodex.com",
    long_description=__doc__,
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
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.6",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
    ],
    test_suite="tests",
    setup_requires=["pytest-runner"],
    tests_require=["pytest", "Flask-Security-Fork"],
)

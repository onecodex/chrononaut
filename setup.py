#!/usr/bin/env python
"""
``chrononaut``
------------

``chrononaut`` is a simple history mixin for SQLAlchemy models,
adding support for audit logging and record locking primitives,
as well as time travel!
"""
from setuptools import setup, find_packages

__version__ = '0.1.0'


setup(
    name='chrononaut',
    version=__version__,  # noqa
    packages=find_packages(exclude=['*test*']),
    install_requires=[''],
    include_package_data=True,
    zip_safe=False,
    dependency_links=[],
    author='Nick Greenfield',
    author_email='opensource@onecodex.com',
    long_description=__doc__,
    license='MIT License',
    keywords='Chrononaut',
    url='https://github.com/onecodex/chrononaut',
    classifiers=[
        'Environment :: Console',
        'License :: OSI Approved :: MIT License',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Internet :: WWW/HTTP',
    ],
    test_suite='tests'
)

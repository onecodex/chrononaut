test:
	psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'chrononaut_test'" | grep -q 1 || psql -U postgres -c "CREATE DATABASE chrononaut_test"
	py.test tests/
	@echo "Successfully passed all tests (one environment only, use tox to full suite)."

lint:
	flake8 --ignore E501 chrononaut/
	flake8 --ignore E501 tests/
	black --check -l 100 chrononaut/ tests/
	@echo "Successfully linted all files."

coverage:
	py.test --cov-report=term-missing --cov=chrononaut tests/

coveragehtml:
	py.test --cov-report=html --cov=chrononaut tests/

install:
	python setup.py install

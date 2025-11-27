PYTHON ?= $(shell if [ -x overlay_client/.venv/bin/python ]; then echo overlay_client/.venv/bin/python; else echo python3; fi)

.PHONY: lint typecheck test check

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest

check: lint typecheck test

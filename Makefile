.PHONY: reproduce test lint check

reproduce:
	python run_eval.py

test:
	pytest -q

lint:
	ruff check .

check: lint test

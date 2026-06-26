.PHONY: install demo test scan rules clean

install:
	pip install -r requirements.txt
	pip install -e .

demo:
	python demo/run_demo.py

test:
	pytest -q

rules:
	python -m claritydesk.cli rules

clean:
	rm -rf demo/output build dist *.egg-info src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

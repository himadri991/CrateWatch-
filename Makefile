.PHONY: install run simulate simulate-shock simulate-mixed test load ttr gap report ppt style terraform-check clean

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

run:
	.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

simulate:
	.venv/bin/python -m edge.agent --scenario normal

simulate-shock:
	.venv/bin/python -m edge.agent --scenario shock

simulate-mixed:
	.venv/bin/python -m edge.agent --scenario mixed

test:
	.venv/bin/pytest -q

load:
	.venv/bin/python scripts/load_test.py

ttr:
	.venv/bin/python scripts/failure_demo.py

gap:
	.venv/bin/python scripts/gap_demo.py

report:
	.venv/bin/python scripts/sla_report.py

ppt:
	.venv/bin/python scripts/generate_ppt.py

style:
	.venv/bin/python scripts/style_check.py

terraform-check:
	.venv/bin/python scripts/check_terraform.py

clean:
	rm -rf data/*.db data/*.db-* __pycache__ app/__pycache__ edge/__pycache__ tests/__pycache__ .pytest_cache

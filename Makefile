.PHONY: paper paper-fast test test-backend test-frontend

paper:
	./scripts/reproduce_paper.sh

paper-fast:
	./scripts/reproduce_paper.sh --fast

test: test-backend test-frontend

test-backend:
	cd backend && .venv/bin/pytest -q

test-frontend:
	cd frontend && npm test -- --run

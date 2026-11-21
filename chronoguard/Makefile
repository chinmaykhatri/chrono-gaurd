.PHONY: bootstrap data up down test verifier-test console-test gateway-test migrate eval bench

bootstrap:
	uv run --project verifier python scripts/bootstrap.py

data: bootstrap
	docker compose --env-file .env -f deploy/compose.data.yml up -d --wait

up: bootstrap
	docker compose up --build -d --wait

down:
	docker compose down

test: verifier-test console-test gateway-test

verifier-test:
	cd verifier && uv run pytest -q

console-test:
	cd console && npm run build && npm test

gateway-test:
	python bifrost/prepare.py
	cd bifrost/plugins/chronoguard && go test ./front/... ./back/... ./internal/...

migrate:
	docker compose run --rm verifier alembic upgrade head

eval:
	python eval/run_eval.py

bench:
	cd bifrost/plugins/chronoguard/front && go test -bench=.
	cd bifrost/plugins/chronoguard/internal/decide && go test -bench=.
	python eval/run_eval.py

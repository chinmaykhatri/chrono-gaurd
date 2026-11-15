.PHONY: bootstrap data up down test verifier-test console-test gateway-test migrate eval demo-reset bench seed

bootstrap:
	uv run --project verifier python scripts/bootstrap.py

data:
	docker compose --env-file .env -f deploy/compose.data.yml up -d --wait

up:
	docker compose up --build -d --wait

down:
	docker compose down

test: verifier-test console-test gateway-test

verifier-test:
	cd verifier && uv run pytest -q

console-test:
	cd console && npm run build && npm test

gateway-test:
	cd bifrost/plugins/chronoguard && go test ./front/... ./back/... ./internal/...

migrate:
	docker compose run --rm verifier alembic upgrade head

eval:
	python eval/run_eval.py

demo-reset:
	@echo "Resetting ChronoGuard demo state (clock, Redis manifests, cache)..."
	python -c "import redis; r = redis.from_url('redis://localhost:6379/0'); [r.delete(k) for k in r.keys('cg:*') if not k.startswith(b'cg:session:')]; r.hset('cg:clock', mapping={'mode':'real','offset_seconds':'0'}); print('Demo state reset successfully.')"

bench:
	cd bifrost/plugins/chronoguard/front && go test -bench=.
	cd bifrost/plugins/chronoguard/internal/decide && go test -bench=.
	python eval/run_eval.py

seed:
	python -c "from app.eval_runner import eval_service; print(f'Loaded {len(eval_service.list_datasets())} datasets and {len(eval_service.list_runs())} runs.')"

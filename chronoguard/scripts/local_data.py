"""Run a verifier command against isolated local integration data stores.

Usage: uv run --project verifier python scripts/local_data.py alembic upgrade head
       uv run --project verifier python scripts/local_data.py pytest -q
The child receives secrets through its environment, never command-line arguments.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote

from dotenv import dotenv_values


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    config = {key: value for key, value in dotenv_values(root / '.env').items() if value is not None}
    env = os.environ.copy()
    env.update(config)
    for key in ('POSTGRES_PASSWORD', 'REDIS_PASSWORD'):
        if not config.get(key):
            raise SystemExit('Local datastore credentials are missing; run bootstrap.py.')
    env['CG_DATABASE_URL'] = 'postgresql+asyncpg://chronoguard:' + quote(config['POSTGRES_PASSWORD'], safe='') + '@127.0.0.1:55432/chronoguard'
    env['CG_REDIS_URL'] = 'redis://:' + quote(config['REDIS_PASSWORD'], safe='') + '@127.0.0.1:56379/0'
    env['CG_BIFROST_URL'] = 'http://127.0.0.1:8080'
    env['CG_ENVIRONMENT'] = 'development'
    args = sys.argv[1:]
    if not args:
        raise SystemExit('Pass a verifier command, such as alembic upgrade head.')
    raise SystemExit(subprocess.call(['uv', 'run', '--frozen', *args], cwd=root / 'verifier', env=env))


if __name__ == '__main__':
    main()

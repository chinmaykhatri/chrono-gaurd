"""Create local secrets without printing their values or overwriting configured keys."""
from __future__ import annotations

import os
from pathlib import Path
import secrets

from argon2 import PasswordHasher


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = root / '.env'
    content = target.read_text(encoding='utf-8') if target.exists() else ''
    names = {}
    for line in content.splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            names[key.strip()] = value.strip().strip("'\"")
    defaults = {
        'CG_ENVIRONMENT': 'development',
        'CG_CONSOLE_ORIGIN': 'http://localhost:3000',
        'CG_INTERNAL_KEY': secrets.token_urlsafe(48),
        'CG_SESSION_SECRET': secrets.token_urlsafe(48),
        'POSTGRES_PASSWORD': secrets.token_urlsafe(32),
        'REDIS_PASSWORD': secrets.token_urlsafe(32),
        'CG_STORE_CONTENT': 'false',
        'CG_ALLOW_SIMULATED_CLOCK': 'true',
        'CG_RETENTION_DAYS': '7',
    }
    if not names.get('CG_ADMIN_PASSWORD_HASH'):
        password = secrets.token_urlsafe(24)
        password_file = root / '.admin-password'
        if password_file.exists():
            raise SystemExit('Existing .admin-password found without configured hash; reconcile it manually.')
        fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(password + '\n')
        defaults['CG_ADMIN_PASSWORD_HASH'] = PasswordHasher().hash(password)
    # Explicit dotenv values remain authoritative. Only copy provider credentials
    # already available to this process; never print or probe their value.
    for key in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'TAVILY_API_KEY'):
        if os.environ.get(key) and not names.get(key):
            defaults[key] = os.environ[key]
    updated = []
    for line in content.splitlines():
        key = line.split('=', 1)[0].strip() if '=' in line else ''
        if key in defaults and not names.get(key):
            continue
        updated.append(line)
    for key, value in defaults.items():
        if not names.get(key):
            # Single quoting prevents Compose from expanding Argon2 '$' segments.
            updated.append(f"{key}='{value}'")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write('\n'.join(updated) + '\n')
    if os.name != 'nt':
        target.chmod(0o600)
    print('Local .env prepared. Generated admin password is in .admin-password.')
    print('Neither secret file belongs in version control.')


if __name__ == '__main__':
    main()

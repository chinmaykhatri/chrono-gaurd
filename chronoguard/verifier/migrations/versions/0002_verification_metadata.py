"""Migrate pre-release databases that predate guard, delta, and shadow metadata."""

from alembic import op
import sqlalchemy as sa

from app import db


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {
        db.requests: ("decision_shadow", "shadow_reason", "guard_tripped", "guard_reason", "query_signature"),
        db.facts: (
            "source_urls", "source_text_hash", "window_hash", "last_extracted_at", "delta_confirmed",
            "delta_saved_credits", "n_checks", "n_changed", "query_hits", "lambda_hat", "optimal_interval_s",
        ),
        db.claims: ("source_urls", "source_text_hash", "delta_confirmed"),
    }
    for table, names in columns.items():
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        for name in names:
            if name not in existing:
                op.add_column(table.name, sa.Column(name, table.c[name].type, nullable=True))


def downgrade():
    # Upgrade accepts databases where some or all fields already existed at 0001.
    # Keeping those fields avoids destroying previous data on rollback.
    pass

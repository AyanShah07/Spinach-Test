"""Initial schema, including safe adoption of the unversioned assessment demo."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    metadata = sa.MetaData()
    sa.Table("customers", metadata,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("attributes", JSONB, nullable=False),
        *[sa.Column(f"{ch}_opt_in", sa.Boolean, nullable=False) for ch in ("email", "sms", "whatsapp", "push")],
        sa.Column("last_active", sa.DateTime(timezone=True)),
        sa.Column("has_converted", sa.Boolean, nullable=False))
    sa.Table("events", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.String(128), nullable=False, unique=True, index=True),
        sa.Column("customer_id", sa.String(64), sa.ForeignKey("customers.id"), nullable=False, index=True),
        sa.Column("channel", sa.String(32), nullable=False, index=True),
        sa.Column("event_type", sa.String(32), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False, index=True))
    sa.Table("engagement_scores", metadata,
        sa.Column("customer_id", sa.String(64), sa.ForeignKey("customers.id"), primary_key=True),
        sa.Column("score", sa.Float, nullable=False, index=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("channel_breakdown", JSONB, nullable=False))
    sa.Table("campaigns", metadata,
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("name", sa.String(256), nullable=False),
        sa.Column("objective", sa.String(64), nullable=False), sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("audience_size", sa.Integer, nullable=False))
    sa.Table("campaign_metrics", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("campaign_id", sa.String(64), sa.ForeignKey("campaigns.id"), nullable=False, index=True),
        sa.Column("metric_name", sa.String(64), nullable=False), sa.Column("value", sa.Float, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    sa.Table("dlq_events", metadata,
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("event_id", sa.String(128), nullable=False, index=True),
        sa.Column("payload", JSONB, nullable=False), sa.Column("failure_reason", sa.Text, nullable=False),
        sa.Column("retry_count", sa.Integer, nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("replayed_at", sa.DateTime(timezone=True)))
    sa.Table("event_outbox", metadata,
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("event_id", sa.String(128), nullable=False, index=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), index=True))
    # checkfirst adopts existing tables without dropping customer data.
    bind = op.get_bind()
    metadata.create_all(bind, checkfirst=True)
    inspector = sa.inspect(bind)
    if "replayed_at" not in {c["name"] for c in inspector.get_columns("dlq_events")}:
        op.add_column("dlq_events", sa.Column("replayed_at", sa.DateTime(timezone=True)))
    for channel in ("email", "sms", "whatsapp", "push"):
        sa.Index(f"ix_customers_{channel}_eligibility", metadata.tables["customers"].c[f"{channel}_opt_in"],
                 metadata.tables["customers"].c.has_converted, metadata.tables["customers"].c.last_active,
                 metadata.tables["customers"].c.id).create(bind, checkfirst=True)
    sa.Index("ix_events_customer_channel_type_time", *[metadata.tables["events"].c[col]
             for col in ("customer_id", "channel", "event_type", "timestamp")]).create(bind, checkfirst=True)

def downgrade():
    raise RuntimeError("Destructive initial-schema downgrade is disabled; restore a verified backup instead")

"""Track published stream IDs to distinguish backlog from Redis data loss."""
from alembic import op
import sqlalchemy as sa
revision = "002_outbox_message_id"
down_revision = "001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("event_outbox", sa.Column("message_id", sa.String(128), nullable=True))

def downgrade():
    op.drop_column("event_outbox", "message_id")

"""Saved-script preferences and persistent tool-call history."""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('chats', 'assistant_profiles'):
        op.add_column(table, sa.Column('script_tools_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('messages', sa.Column('tool_calls', sa.JSON(), nullable=True))
    op.add_column('messages', sa.Column('tool_name', sa.String(), nullable=False, server_default=''))


def downgrade():
    op.drop_column('messages', 'tool_name')
    op.drop_column('messages', 'tool_calls')
    op.drop_column('assistant_profiles', 'script_tools_enabled')
    op.drop_column('chats', 'script_tools_enabled')

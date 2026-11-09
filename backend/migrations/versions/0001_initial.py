"""Initial chat storage."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('chats', sa.Column('id', sa.String(), primary_key=True), sa.Column('title', sa.String(), nullable=False), sa.Column('model', sa.String(), nullable=False), sa.Column('updated_at', sa.String(), nullable=False))
    op.create_table('messages', sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True), sa.Column('chat_id', sa.String(), sa.ForeignKey('chats.id'), nullable=False), sa.Column('role', sa.String(), nullable=False), sa.Column('content', sa.Text(), nullable=False), sa.Column('model', sa.String(), nullable=False), sa.Column('status', sa.String(), nullable=False), sa.Column('created_at', sa.String(), nullable=False))
    op.create_index('ix_messages_chat_id', 'messages', ['chat_id'])


def downgrade():
    op.drop_table('messages')
    op.drop_table('chats')

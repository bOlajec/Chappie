"""Saved assistant profiles and chat-specific settings."""
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    profiles = op.create_table('assistant_profiles',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=False),
        sa.Column('project_context', sa.Text(), nullable=False),
        sa.Column('reference_notes', sa.Text(), nullable=False),
        sa.Column('preferred_model', sa.String(), nullable=False),
        sa.Column('reasoning', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False))
    op.add_column('chats', sa.Column('assistant_id', sa.String(), nullable=True))
    op.add_column('chats', sa.Column('assistant_snapshot', sa.JSON(), nullable=True))
    op.add_column('chats', sa.Column('project_context', sa.Text(), nullable=False, server_default=''))
    op.add_column('chats', sa.Column('reasoning', sa.String(), nullable=False, server_default='off'))
    op.create_index('ix_chats_assistant_id', 'chats', ['assistant_id'])
    op.bulk_insert(profiles, [{
        'id': 'arduino-developer', 'name': 'Arduino Developer',
        'description': 'Arduino sketches, wiring context, and library-aware help.',
        'instructions': (
            'Help the user develop Arduino sketches for their specific board and components. '
            'Use the project context for board, pin assignments, libraries, and constraints. '
            'Ask a concise clarifying question when missing board, wiring, or library details '
            'would materially change the solution; do not invent them. '
            'Return one complete Arduino C++ sketch with setup() and loop() when appropriate. '
            'Use documented library APIs from the supplied references and identify uncertainty '
            'instead of fabricating functions. Prefer straightforward, maintainable code and '
            'non-blocking timing when the task requires concurrent behavior. '
            'Give code only when code is requested, unless clarification is necessary. '
            'Explain wiring or code when the user explicitly asks. '
            'Never claim a sketch was compiled, tested on hardware, or uploaded: this assistant '
            'has no compiler, board connection, or tool execution.'),
        'project_context': '', 'reference_notes': '', 'preferred_model': '',
        'reasoning': 'off', 'updated_at': datetime.now(timezone.utc).isoformat(),
    }])


def downgrade():
    op.drop_index('ix_chats_assistant_id', table_name='chats')
    for column in ['reasoning', 'project_context', 'assistant_snapshot', 'assistant_id']:
        op.drop_column('chats', column)
    op.drop_table('assistant_profiles')

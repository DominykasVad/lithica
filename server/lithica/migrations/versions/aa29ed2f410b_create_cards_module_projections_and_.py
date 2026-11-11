'''
Create cards module projections and lorebook links

Revision ID: aa29ed2f410b
Created at: 2026-11-11 22:20:14.965510
'''

import sqlalchemy as sa
from alembic import op



revision = 'aa29ed2f410b'
down_revision = 'b4c9d0e1f2a3'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table('cards_card',
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('spec', sa.Unicode(length=32), nullable=False),
    sa.Column('name', sa.Unicode(length=200), nullable=False),
    sa.Column('creator', sa.Unicode(length=200), nullable=False),
    sa.Column('greetings', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['post_id'], ['post.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('post_id')
    )
    op.create_table('cards_card_lorebook',
    sa.Column('card_post_id', sa.Integer(), nullable=False),
    sa.Column('lorebook_post_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['card_post_id'], ['post.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['lorebook_post_id'], ['post.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('card_post_id', 'position'),
    sa.UniqueConstraint('card_post_id', 'lorebook_post_id', name='uq_cards_card_lorebook')
    )
    op.create_index(op.f('ix_cards_card_lorebook_lorebook_post_id'), 'cards_card_lorebook', ['lorebook_post_id'], unique=False)
    op.create_table('cards_lorebook',
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Unicode(length=200), nullable=False),
    sa.Column('entries', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['post_id'], ['post.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('post_id')
    )

def downgrade() -> None:
    op.drop_table('cards_lorebook')
    op.drop_index(op.f('ix_cards_card_lorebook_lorebook_post_id'), table_name='cards_card_lorebook')
    op.drop_table('cards_card_lorebook')
    op.drop_table('cards_card')

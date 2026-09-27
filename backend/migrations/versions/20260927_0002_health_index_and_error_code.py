"""add health_index and error_code to diagnoses

Revision ID: 20260927_0002
Revises: 6b48ca53b5bb
Create Date: 2026-09-27 22:10:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260927_0002'
down_revision = '6b48ca53b5bb'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('diagnoses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('health_index', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('error_code', sa.String(length=24), nullable=True))


def downgrade():
    with op.batch_alter_table('diagnoses', schema=None) as batch_op:
        batch_op.drop_column('error_code')
        batch_op.drop_column('health_index')

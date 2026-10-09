"""create static_analyses table

Revision ID: 20261009_0003
Revises: 20260927_0002
Create Date: 2026-10-09 08:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '20261009_0003'
down_revision = '20260927_0002'
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")
BIGID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade():
    op.create_table(
        'static_analyses',
        sa.Column('id', BIGID, primary_key=True, autoincrement=True),
        sa.Column('user', sa.String(length=64), nullable=False, index=True),
        sa.Column('ts', TS, nullable=False),
        sa.Column('motor_id', sa.Integer(), sa.ForeignKey('motors.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('inputs_json', sa.JSON(), nullable=False),
        sa.Column('result_json', sa.JSON(), nullable=False),
        sa.Column('fault_type', sa.String(length=40), nullable=False),
        sa.Column('severity', sa.Float(), nullable=False),
        sa.Column('mhi', sa.Float(), nullable=False),
        sa.Column('request_id', sa.String(length=64), unique=True, nullable=True),
    )
    op.create_index('ix_static_analyses_user_ts', 'static_analyses', ['user', 'ts'])


def downgrade():
    op.drop_index('ix_static_analyses_user_ts', table_name='static_analyses')
    op.drop_table('static_analyses')

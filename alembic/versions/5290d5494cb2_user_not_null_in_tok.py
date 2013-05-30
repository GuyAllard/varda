"""User not null in token model

Revision ID: 5290d5494cb2
Revises: 85934b9f4e3
Create Date: 2013-05-30 11:41:19.370950

"""

# revision identifiers, used by Alembic.
revision = '5290d5494cb2'
down_revision = '85934b9f4e3'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('token', u'user_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('token', u'user_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    ### end Alembic commands ###

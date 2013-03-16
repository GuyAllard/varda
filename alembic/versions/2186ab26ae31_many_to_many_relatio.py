"""Many-to-many relationships on annotation model

Revision ID: 2186ab26ae31
Revises: 454bdc604dcd
Create Date: 2013-03-15 13:15:01.465877

"""

# revision identifiers, used by Alembic.
revision = '2186ab26ae31'
down_revision = '454bdc604dcd'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('sample_frequency',
    sa.Column('annotation_id', sa.Integer(), nullable=True),
    sa.Column('sample_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['annotation_id'], ['annotation.id'], ),
    sa.ForeignKeyConstraint(['sample_id'], ['sample.id'], ),
    sa.PrimaryKeyConstraint()
    )
    op.drop_table(u'local_frequency')
    op.add_column('annotation', sa.Column('global_frequency', sa.Boolean(), nullable=True))
    op.drop_column('annotation', u'global_frequencies')
    op.drop_column('exclude', u'id')
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column('exclude', sa.Column(u'id', sa.INTEGER(), server_default=u"nextval('exclude_id_seq'::regclass)", nullable=False))
    op.add_column('annotation', sa.Column(u'global_frequencies', sa.BOOLEAN(), nullable=True))
    op.drop_column('annotation', 'global_frequency')
    op.create_table(u'local_frequency',
    sa.Column(u'id', sa.INTEGER(), server_default="nextval('local_frequency_id_seq'::regclass)", nullable=False),
    sa.Column(u'annotation_id', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column(u'sample_id', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column(u'label', sa.VARCHAR(length=200), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['annotation_id'], [u'annotation.id'], name=u'local_frequency_annotation_id_fkey'),
    sa.ForeignKeyConstraint(['sample_id'], [u'sample.id'], name=u'local_frequency_sample_id_fkey'),
    sa.PrimaryKeyConstraint(u'id', name=u'local_frequency_pkey')
    )
    op.drop_table('sample_frequency')
    ### end Alembic commands ###
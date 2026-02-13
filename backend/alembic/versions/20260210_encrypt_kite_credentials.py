"""Encrypt KiteCredentials - rename columns for encrypted storage

Revision ID: 20260210_encrypt
Revises: dedf72726e7d
Create Date: 2026-02-10 20:45:00.000000

This migration:
1. Renames api_secret -> api_secret_encrypted
2. Renames access_token -> access_token_encrypted
3. Increases column size to accommodate encrypted data (500 chars)

Note: Existing plaintext data will need to be re-encrypted after migration.
Run the encrypt_existing_credentials.py script after this migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260210_encrypt'
down_revision: Union[str, None] = 'dedf72726e7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename api_secret to api_secret_encrypted and increase size
    op.alter_column(
        'kite_credentials',
        'api_secret',
        new_column_name='api_secret_encrypted',
        type_=sa.String(500),
        existing_type=sa.String(50),
        existing_nullable=False
    )
    
    # Rename access_token to access_token_encrypted and increase size
    op.alter_column(
        'kite_credentials',
        'access_token',
        new_column_name='access_token_encrypted',
        type_=sa.String(500),
        existing_type=sa.String(100),
        existing_nullable=False
    )


def downgrade() -> None:
    # Rename back to original names
    op.alter_column(
        'kite_credentials',
        'api_secret_encrypted',
        new_column_name='api_secret',
        type_=sa.String(50),
        existing_type=sa.String(500),
        existing_nullable=False
    )
    
    op.alter_column(
        'kite_credentials',
        'access_token_encrypted',
        new_column_name='access_token',
        type_=sa.String(100),
        existing_type=sa.String(500),
        existing_nullable=False
    )

"""Initialize a company's first Office administrator using an existing account ID."""
import argparse
import asyncio
from getpass import getpass

from pwdlib import PasswordHash

from sqlalchemy.ext.asyncio import create_async_engine

from ..runtime.settings import database_url_from_environment
from .repository import Identity, OfficeRepository


async def initialize(args):
    url = database_url_from_environment(load_env_file=True)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(url)
    try:
        repository = OfficeRepository(engine)
        await repository.create_schema()
        password = getpass('Office administrator password: ')
        if not 12 <= len(password) <= 256:
            raise ValueError('Office password must be 12 to 256 characters.')
        actor = Identity(args.database, args.company, args.user)
        password_hash = await asyncio.to_thread(PasswordHash.recommended().hash, password)
        if args.reset_password:
            await repository.reset_password(actor, actor.user, password_hash)
        else:
            await repository.bootstrap(actor, args.name, password_hash=password_hash)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--user", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--name", help="Display name of the first administrator")
    mode.add_argument("--reset-password", action="store_true", help="Set a password for an existing enabled administrator")
    asyncio.run(initialize(parser.parse_args()))

from sqlalchemy import (
    JSON, BigInteger, Boolean, Column, ForeignKey, Integer, MetaData, String, Table, Text,
    UniqueConstraint, inspect, text,
)

metadata = MetaData()

companies = Table(
    "office_companies", metadata,
    Column("id", String(64), primary_key=True),
    Column("database", String(256), nullable=False),
    Column("company", String(256), nullable=False),
    UniqueConstraint("database", "company"),
)
users = Table(
    "office_users", metadata,
    Column("company", ForeignKey("office_companies.id"), primary_key=True),
    Column("user", String(256), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("role", String(16), nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("version", Integer, nullable=False),
)
credentials = Table(
    "office_credentials", metadata,
    Column("company", ForeignKey("office_companies.id"), primary_key=True),
    Column("user", String(256), primary_key=True),
    Column("password_hash", Text, nullable=False),
)
sessions = Table(
    "office_sessions", metadata,
    Column("token", String(64), primary_key=True),
    Column("company", ForeignKey("office_companies.id"), nullable=False),
    Column("user", String(256), nullable=False),
    Column("version", Integer, nullable=False),
    Column("expires", Integer, nullable=False),
)
spaces = Table(
    "office_spaces", metadata,
    Column("id", String(36), primary_key=True),
    Column("company", ForeignKey("office_companies.id"), nullable=False),
    Column("name", String(200), nullable=False),
    Column("personal_user", String(256)),
    Column("archived", Boolean, nullable=False),
    UniqueConstraint("company", "personal_user"),
)
members = Table(
    "office_members", metadata,
    Column("space", ForeignKey("office_spaces.id"), primary_key=True),
    Column("user", String(256), primary_key=True),
    Column("role", String(16), nullable=False),
)
source_grants = Table(
    "office_source_grants", metadata,
    Column("space", ForeignKey("office_spaces.id"), primary_key=True),
    Column("source", String(64), primary_key=True),
    Column("tables", JSON, nullable=False),
)
source_member_limits = Table(
    "office_source_member_limits", metadata,
    Column("space", ForeignKey("office_spaces.id"), primary_key=True),
    Column("source", String(64), primary_key=True),
    Column("user", String(256), primary_key=True),
    Column("tables", JSON, nullable=False),
)
audit = Table(
    "office_audit", metadata,
    Column("id", String(36), primary_key=True),
    Column("company", ForeignKey("office_companies.id"), nullable=False),
    Column("user", String(256), nullable=False),
    Column("action", String(64), nullable=False),
    Column("details", JSON, nullable=False),
    Column("created", Integer, nullable=False),
)

folders = Table(
    "office_folders", metadata,
    Column("id", String(36), primary_key=True),
    Column("space", ForeignKey("office_spaces.id"), nullable=False),
    Column("parent", String(36)),
    Column("name", String(200), nullable=False),
)
files = Table(
    "office_files", metadata,
    Column("id", String(36), primary_key=True),
    Column("space", ForeignKey("office_spaces.id"), nullable=False),
    Column("folder", String(36)),
    Column("name", String(200), nullable=False),
    Column("format", String(8), nullable=False),
    Column("document", String(256), nullable=False, unique=True),
    Column("revision", Integer, nullable=False),
    Column("scope", JSON, nullable=False),
    Column("version", Integer, nullable=False),
    Column("deleted", Boolean, nullable=False),
    Column("created_by", String(256), nullable=False),
)
file_preferences = Table(
    "office_file_preferences", metadata,
    Column("file", ForeignKey("office_files.id"), primary_key=True),
    Column("user", String(256), primary_key=True),
    Column("starred", Boolean, nullable=False),
    Column("favorite_group", String(80)),
    Column("seen", BigInteger, nullable=False),
)

file_search_text = Table(
    "office_file_search_text", metadata,
    Column("file", ForeignKey("office_files.id", ondelete="CASCADE"), primary_key=True),
    Column("revision", Integer, nullable=False),
    Column("body", Text, nullable=False),
)

knowledge_turns = Table(
    "office_knowledge_turns", metadata,
    Column("id", String(36), primary_key=True),
    Column("space", ForeignKey("office_spaces.id"), nullable=False),
    Column("user", String(256), nullable=False),
    Column("conversation", String(36), nullable=False, server_default="default"),
    Column("question", Text, nullable=False),
    Column("answer", Text, nullable=False),
    Column("citations", JSON, nullable=False),
    Column("sources", JSON, nullable=False),
    Column("created", BigInteger, nullable=False),
)


knowledge_deleted = Table(
    "office_knowledge_deleted", metadata,
    Column("space", ForeignKey("office_spaces.id"), primary_key=True),
    Column("user", String(256), primary_key=True),
    Column("conversation", String(36), primary_key=True),
)


settings = Table(
    "office_settings", metadata,
    Column("company", ForeignKey("office_companies.id"), primary_key=True),
    Column("owner", String(300), primary_key=True),
    Column("version", Integer, nullable=False),
    Column("document", JSON, nullable=False),
)


def initialize_schema(connection):
    """Create a new library or upgrade the known PostgreSQL prototype schema."""
    if connection.dialect.name != "postgresql":
        metadata.create_all(connection)
        if connection.dialect.name == "sqlite":
            if not any(column["name"] == "favorite_group" for column in inspect(connection).get_columns(file_preferences.name)):
                connection.execute(text("ALTER TABLE office_file_preferences ADD COLUMN favorite_group VARCHAR(80)"))
            columns = inspect(connection).get_columns(knowledge_turns.name)
            if not any(column["name"] == "conversation" for column in columns):
                connection.execute(text(
                    "ALTER TABLE office_knowledge_turns ADD COLUMN conversation VARCHAR(36) NOT NULL DEFAULT 'default'"
                ))
        return

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    connection.execute(text("SELECT pg_advisory_xact_lock(721681226404539821)"))
    metadata.create_all(connection)
    schema = connection.get_execution_options().get("schema_translate_map", {}).get(None)
    inspector = inspect(connection)
    operations = Operations(MigrationContext.configure(connection))
    for table, field in ((file_preferences, "seen"), (knowledge_turns, "created")):
        current_type = next(column["type"] for column in inspector.get_columns(table.name, schema=schema)
                            if column["name"] == field)
        if isinstance(current_type, Integer) and not isinstance(current_type, BigInteger):
            operations.alter_column(table.name, field, type_=BigInteger(), schema=schema)

    if not any(column["name"] == "favorite_group" for column in inspector.get_columns(file_preferences.name, schema=schema)):
        operations.add_column(file_preferences.name, Column("favorite_group", String(80)), schema=schema)

    columns = inspector.get_columns(knowledge_turns.name, schema=schema)
    if not any(column["name"] == "conversation" for column in columns):
        operations.add_column(knowledge_turns.name,
            Column("conversation", String(36), nullable=False, server_default="default"), schema=schema)
    if not any(column["name"] == "sources" for column in columns):
        operations.add_column(knowledge_turns.name, Column("sources", JSON), schema=schema)
        # Older rows recorded citations only. They cannot prove which other files the model read.
        connection.execute(knowledge_turns.update().values(
            answer="历史回答缺少完整来源记录，请重新提问。", citations=[], sources=[],
        ))
        operations.alter_column(knowledge_turns.name, "sources", nullable=False, schema=schema)

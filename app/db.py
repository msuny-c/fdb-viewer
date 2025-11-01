import os, json, datetime as dt, secrets, string
from sqlalchemy import create_engine, MetaData, Table, Column, String, Text, DateTime
from sqlalchemy.engine import Engine
from sqlalchemy.sql import select

DEFAULT_DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")

def make_engine() -> Engine:
    connect_args = {}
    if DEFAULT_DB_URL.startswith("sqlite"):
        os.makedirs("./data", exist_ok=True)
        connect_args = {"check_same_thread": False}
    return create_engine(DEFAULT_DB_URL, future=True, pool_pre_ping=True, connect_args=connect_args)

metadata = MetaData()

documents = Table(
    "documents", metadata,
    Column("id", String(8), primary_key=True),
    Column("title", String(200), nullable=True),
    Column("json", Text, nullable=False),
    Column("created_at", DateTime, default=dt.datetime.utcnow, nullable=False),
)

def init_db(engine: Engine):
    metadata.create_all(engine)

_ALPH = string.ascii_lowercase + string.digits
def gen_id(length: int = 8) -> str:
    return ''.join(secrets.choice(_ALPH) for _ in range(length))

def insert_doc(engine: Engine, data: dict, title: str | None) -> str:
    doc_id = gen_id(8)
    with engine.begin() as conn:
        conn.execute(documents.insert().values(
            id=doc_id, title=title, json=json.dumps(data, ensure_ascii=False),
        ))
    return doc_id

def get_doc(engine: Engine, doc_id: str) -> dict | None:
    with engine.begin() as conn:
        row = conn.execute(select(documents.c.id, documents.c.title, documents.c.json, documents.c.created_at)
                           .where(documents.c.id == doc_id)).fetchone()
        if not row: return None
        return {"id": row.id, "title": row.title, "json": json.loads(row.json), "created_at": row.created_at}

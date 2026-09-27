from .database import Base, engine
from . import models
if __name__ == "__main__":
    Base.metadata.create_all(engine)
    if engine.url.get_backend_name() == "postgresql":
        from sqlalchemy import text, inspect
        with engine.begin() as conn:
            cols = {c["name"] for c in inspect(engine).get_columns("transactions")}
            if "financial_year" not in cols: conn.execute(text("ALTER TABLE transactions ADD COLUMN financial_year VARCHAR(9) DEFAULT '2026-27' NOT NULL"))

"""Reset the database to a fresh demo world:  uv run python -m app.seed"""

from sqlmodel import Session

from app.clock import clock, parse_utc
from app.config import get_settings
from app.db import get_engine, init_db
from app.seed.generator import seed_database

if __name__ == "__main__":
    settings = get_settings()
    if settings.now:
        clock.freeze(parse_utc(settings.now))
    init_db()
    with Session(get_engine()) as session:
        info = seed_database(session, clock.now(), settings.seed)
    print(f"Seeded demo world: {info}")

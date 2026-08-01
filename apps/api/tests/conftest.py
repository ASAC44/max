import pytest
from sqlalchemy.orm import sessionmaker

from max_api.db import Base, build_engine


@pytest.fixture
def session(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as value:
        yield value
    engine.dispose()

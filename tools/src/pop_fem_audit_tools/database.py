# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""The database connection.

"""
from functools import cached_property
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from .config import Settings, get_settings


class Base(DeclarativeBase):
    """The base data model."""


class DataSource:
    """A data source."""

    @cached_property
    def engine(self) -> sa.Engine:
        """Returns the database engine.

        :return: The database engine.
        """
        settings: Settings = get_settings()
        return self.__create_engine(settings.SQLALCHEMY_DATABASE_URL)

    @cached_property
    def __session_local(self) -> sessionmaker:
        """Returns the callable to connect and return the database session.

        :return: The callable to connect and return the database session.
        """
        return sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine)

    def get_db(self) -> Session:
        """Connects and returns the database session.

        :return: The database session.
        """
        return self.__session_local()

    @classmethod
    def __create_engine(cls, url: str) -> sa.Engine:
        """Constructs and returns the database engine.

        The foreign key enforcement is enabled on every connection
        of a SQLite engine.

        :param url: The SQLAlchemy database URL.
        :return: The database engine.
        """
        url = cls.__resolve_sqlite_relative_url(url)
        engine: sa.Engine
        if url == "sqlite://":
            engine = sa.create_engine(
                url, connect_args={"check_same_thread": False},
                poolclass=sa.StaticPool)
        else:
            engine = sa.create_engine(url)
        if engine.url.get_backend_name() == "sqlite":
            sa.event.listen(engine, "connect",
                            cls.__enable_sqlite_foreign_keys)
        return engine

    @staticmethod
    def __enable_sqlite_foreign_keys(dbapi_connection: Any,
                                     _: Any) -> None:
        """Enables the foreign key enforcement on a new connection.

        :param dbapi_connection: The DBAPI connection.
        :param _: The connection record (unused).
        :return: None.
        """
        cursor: Any = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @staticmethod
    def __resolve_sqlite_relative_url(url: str) -> str:
        """Resolves the SQLite relative URL to the instance folder.

        :param url: The SQLAlchemy database URL.
        :return: The resolved SQLAlchemy database URL.
        """
        if not url.startswith("sqlite:///"):
            return url
        path: Path = Path(url[len("sqlite:///"):])
        if path.is_absolute():
            return url
        base: Path = Path(__file__).parent.parent
        if base.name == "src":
            base = base.parent
        path = base / "instance" / path
        return f"sqlite:///{path}"


ds: DataSource = DataSource()
"""The data source."""

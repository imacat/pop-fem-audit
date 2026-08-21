# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""The configuration.

"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """The configuration settings."""
    app_name: str = "Tools for A Feminist Audit of Pop Music"
    """The application name."""
    admin_email: str = "imacat@mail.imacat.idv.tw"
    """The administrator email address."""
    SQLALCHEMY_DATABASE_URI: str
    """The SQLAlchemy database URL."""
    ANTHROPIC_API_KEY: str
    """The Anthropic API key."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    """The model configuration."""


__settings: Settings | None = None
"""The configuration settings."""


def get_settings() -> Settings:
    """Returns the configuration settings.

    :return: The configuration settings.
    """
    global __settings
    if __settings is None:
        __settings = Settings()
    return __settings


def set_settings(settings: Settings) -> None:
    """Sets the configuration settings.

    :param settings: The configuration settings.
    :return: None.
    """
    global __settings
    __settings = settings

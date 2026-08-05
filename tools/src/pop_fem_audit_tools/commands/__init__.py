# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/4
"""The registry of the CLI subcommands."""
from .build_db import main as build_db_command
from .export_llm_input import main as export_llm_input_command
from .fetch_artists import main as fetch_artists_command
from .fetch_lyrics import main as fetch_lyrics_command
from .pool_keywords import main as pool_keywords_command
from .run_llm import main as run_llm_command

# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/4
"""The registry of the CLI subcommands."""
from .build_db import main as build_db_command
from .cluster_keywords import main as cluster_keywords_command
from .compare_codings import main as compare_codings_command
from .export_llm_input import main as export_llm_input_command
from .fetch_artists import main as fetch_artists_command
from .fetch_lyrics import main as fetch_lyrics_command
from .run_llm import main as run_llm_command

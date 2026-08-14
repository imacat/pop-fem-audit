# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/4
"""The registry of the CLI subcommands.

Each subcommand is a wrapper that imports its tool module on the
call, so that importing the registry costs nothing but this
module itself.
"""


def build_db_command(argv: list[str] | None = None) -> int:
    """Rebuild the SQLite working store from the inputs.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    from .build_db import main
    return main(argv)


def cluster_keywords_command(argv: list[str] | None = None) -> int:
    """Pool the two tagging runs' keywords and cluster them.

    Writes the five fixed-named artifacts under the output
    directory, creating it (with parents) if it does not exist:
    the pooled keyword text file; then the group membership CSV
    file, holding the clustering result alone; the group name
    keyword text file, holding the same group names as a readable
    list; the coding keyword set JSON file, holding the group
    names plus every extra keyword given via ``--extra-keyword``;
    and the run metadata JSON file, recording the command-line
    choices and the environment.  Each file is written as soon as
    its content is computed, so when the input is rejected, or an
    extra keyword duplicates a group name or another extra
    keyword, the output directory holds whatever the steps before
    the failing one produced, and the error message names what
    failed.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    from .cluster_keywords import main
    return main(argv)


def export_llm_input_command(argv: list[str] | None = None) -> int:
    """Export the LLM input JSONL file from the working store.

    Every song is exported, unless ``--extras-per-id`` is given,
    in which case only the songs its file names are.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    from .export_llm_input import main
    return main(argv)


def fetch_artists_command(argv: list[str] | None = None) -> int:
    """Fetch the artist metadata from Wikidata.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, misses and errors
        included, non-zero on a setup error.
    """
    from .fetch_artists import main
    return main(argv)


def fetch_lyrics_command(argv: list[str] | None = None) -> int:
    """Fetch the missing song lyrics from the public APIs.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, misses included,
        non-zero on a setup error.
    """
    from .fetch_lyrics import main
    return main(argv)


def run_llm_command(argv: list[str] | None = None) -> int:
    """Run one LLM definition file against one input and archive it.

    :param argv: The command-line arguments, or None for ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    from .run_llm import main
    return main(argv)


def tally_codings_command(argv: list[str] | None = None) -> int:
    """Settle the coding by a majority of the three coding runs.

    Writes the final coding table as the given CSV file, holding
    the header row ``Song,Artist Credit,Keyword,Quote`` and one
    row per keyword at least two of the three runs assign, the
    song named by its title and its stored artist credit from the
    SQLite working store, and the keyword carrying the pooled,
    deduplicated, and sorted lyric quotes of the runs that
    assigned it, joined with a single ``|``.  Nothing is written
    when the three archives do not cover the same songs, a record
    is not a successful result, a record's "text" does not parse
    to a JSON object of quote string lists, or a song is not in
    the working store; the error message names what failed.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    from .tally_codings import main
    return main(argv)


def tally_groups_command(argv: list[str] | None = None) -> int:
    """Settle the code groups by a majority of the three runs.

    Writes the final group table as the given CSV file, holding
    the header row ``Group,Keyword,Votes`` and one row per
    (group, keyword) pair at least two of the three selection
    runs select, ordered by the group name and then by the
    keyword.  A selected item that is not in the valid keyword
    list casts no vote.  Nothing is written when the three
    archives do not cover the same groups or a record is
    malformed; the error message names what failed.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    from .tally_groups import main
    return main(argv)

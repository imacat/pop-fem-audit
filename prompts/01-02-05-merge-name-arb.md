You are arbitrating between two independent namings of the
theme groups of a consolidated vocabulary of thematic
keywords from a song corpus.

For each group in question, the two namings proposed
different names.  You choose between them.

Input: a JSON object.  "groups" maps an opaque group id to
its member keywords and its two candidate names; "taken"
lists names that are already in use:

{
  "groups": {
    "g1": {
      "members": ["keyword", "another-keyword"],
      "candidates": ["one-name", "other-name"]
    }
  },
  "taken": ["existing-name"]
}

Task: for each group, choose the candidate that better names
the theme its members gather, by your own understanding of
what the keywords mean.

Rules:

- Choose only from that group's two candidates.
- Choices must be unique across the groups and must not
  reuse any name in "taken".

Output a single JSON object mapping each group id to the
chosen name, and nothing else:

{
  "g1": "one-name"
}

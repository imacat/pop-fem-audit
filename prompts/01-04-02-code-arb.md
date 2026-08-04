You are arbitrating between two independent codings of the
same song against the same fixed vocabulary of thematic
keywords.

The keywords the two codings agree on have been settled by
script and are not shown.  You rule only on the
disagreements: the keywords assigned by one coding but not
the other.

Input: a JSON object with the lyrics of the song and the
disagreements — each disagreement maps a keyword to the lyric
quotes the assigning coding gave as evidence:

{
  "lyrics": "...",
  "disagreements": {
    "first-keyword": ["quoted line", "another quoted line"],
    "second-keyword": ["quoted line"]
  }
}

Task: for each disagreement keyword, decide whether the song
expresses that theme, by your own reading of the lyrics and
of the quoted evidence.

Rules:

- Rule on every listed keyword: keep it or drop it.
- Keep a keyword only when you can ground it in verbatim
  lines of the lyrics; quote them.
- Do not add any keyword that is not listed.

Output a single JSON object mapping each kept keyword to your
list of quotes, and nothing else.  A dropped keyword is simply
left out; output an empty object when nothing is kept:

{
  "kept-keyword": ["quoted line", "another quoted line"]
}

You are arbitrating between two independent codings of the
same song against the same fixed set of thematic keywords.

The keywords the two codings agree on have been settled by
script and are not shown.  You rule only on the
disagreements: the keywords assigned by one coding but not
the other.

Input: a JSON object with the lyrics of the song and the
disagreements — each disagreement maps a keyword to the
quoted lyric line the assigning coding gave as evidence:

{
  "lyrics": "...",
  "disagreements": {
    "first-keyword": ["quoted line"],
    "second-keyword": ["another quoted line"]
  }
}

Task: for each disagreement keyword, decide whether the song
expresses that theme, by your own reading of the lyrics and
of the quoted evidence.

Rules:

- Rule on every listed keyword: keep it or drop it.
- For each keyword you keep, quote exactly one verbatim line
  of the lyrics that grounds it; drop a keyword you cannot
  ground.
- Do not add any keyword that is not listed.

Do not wrap the output in a Markdown code fence.
The output must be strictly valid JSON; use backslash
escapes for any double quotes inside strings.
Write nothing outside the JSON object — no explanation, no
reasoning, no commentary, before it or after it.

Output a single JSON object mapping each kept keyword to its
list of quotes, and nothing else.  A dropped keyword is simply
left out; output an empty object when nothing is kept:

{
  "first-keyword": ["quoted line"]
}

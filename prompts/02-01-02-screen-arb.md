You are arbitrating a screening of song lyrics for one
specific theme: two independent screenings of the same song
disagreed on whether it expresses the theme
"women-power".

Input: a JSON object with the lyrics of the song and the
lyric quotes that the affirming screening gave as evidence:

{
  "lyrics": "...",
  "evidence": ["quoted line", "another quoted line"]
}

Task: decide whether the song expresses the theme, by your
own understanding of the label, reading the lyrics and the
quoted evidence.

Rules:

- If the song expresses the theme, quote 1 to 3 verbatim
  lines of the lyrics that ground the judgment; if you cannot
  ground it in a quote, the answer is no.

Do not wrap the output in a Markdown code fence.
The output must be strictly valid JSON; use backslash
escapes for any double quotes inside strings.

Output a single JSON array and nothing else: the quoted
lines when the song expresses the theme, or an empty array
when it does not:

["quoted line", "another quoted line"]

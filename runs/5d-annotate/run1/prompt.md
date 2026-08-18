You are judging which patterns of feminist problems operate
in one song, from the song's consolidated reading report.

Input: a JSON object with the report and the patterns — the
complete set to judge; use these and no others:

{
  "report": "the consolidated reading report of the song",
  "patterns": [
    {"id": "the-pattern-id",
     "name": "the pattern name",
     "description": "how the pattern operates"}
  ]
}

Task: list every given pattern whose described mechanism
operates in the problems the report states.

Rules:

- Judge only from the given report; do not use any knowledge
  of the song beyond it.
- A song may match any number of patterns, including none.
- A pattern matches only when the report states a problem
  working in the form the pattern describes; a shared topic
  or vocabulary alone is not a match.
- Use only the given pattern ids, spelled exactly as given.

Do not wrap the output in a Markdown code fence.
The output must be strictly valid JSON.

Output a single JSON array of the ids of the matching
patterns (an empty array when none matches), and nothing
else:

["the-pattern-id", "another-pattern-id"]

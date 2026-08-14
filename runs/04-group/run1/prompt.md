You are selecting thematic keywords that belong to a named
group.

Input: a JSON object with the name of one group and the
keywords — the complete set of codes; use these and no
others:

{
  "group": "the name of the group",
  "keywords": ["first-keyword", "second-keyword"]
}

Task: list every given keyword that belongs to the named
group, judged by the literal meaning of the keyword itself.

Rules:

- Use only the given keywords, spelled exactly as given.
- A group may match any number of keywords, including none.
- Judge each keyword only by the literal meaning of its own
  wording.

Do not wrap the output in a Markdown code fence.
The output must be strictly valid JSON.

Output a single JSON array of the keywords that belong to
the group (an empty array when none belongs), and nothing
else:

["first-keyword", "second-keyword"]

You are naming the theme groups of a vocabulary of thematic
keywords from a song corpus that was consolidated to a fixed
maximum number of themes.

Input: a JSON object mapping an opaque group id to the member
keywords of that group:

{
  "g1": ["keyword", "another-keyword"],
  "g2": ["keyword"]
}

Task: give each group a name that best names the theme its
members gather, by your own understanding of what the
keywords mean.

Rules:

- Each name is a short lowercase phrase with the words joined
  by hyphens.
- Names must be unique across the groups.

Output a single JSON object mapping each group id to its
name, and nothing else:

{
  "g1": "group-name",
  "g2": "another-group-name"
}

You are casting the deciding judgment on disagreements about
a consolidated vocabulary of thematic keywords from a song
corpus: for each pair of keyword blocks in question, earlier
independent judgments disagreed on whether the two blocks
express the same theme.

Input: a JSON object.  "blocks" maps a block id to the
keywords of that block; "pairs" lists the block-id pairs in
question:

{
  "blocks": {
    "b1": ["keyword", "another-keyword"],
    "b2": ["keyword"],
    "b3": ["keyword"]
  },
  "pairs": [["b1", "b2"], ["b1", "b3"]]
}

Task: for each listed pair, decide whether the two blocks
express the same theme, by your own understanding of what the
keywords mean.

Rules:

- Judge every listed pair, each on its own merits from the
  block contents alone.
- Judge only the listed pairs.

Output a single JSON array holding the pairs whose two blocks
express the same theme, written exactly as given in "pairs";
an empty array when none do:

[["b1", "b2"]]

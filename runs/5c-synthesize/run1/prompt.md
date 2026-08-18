You are inducing the recurring patterns in how the problems
appear across the consolidated reading reports of many songs.

Input: a JSON object keyed by song ID (such as "song-11"),
each value the consolidated reading report of that song; a
report of 「無」 means no problem was found for that song.

{
  "song-11": "consolidated report ...",
  "song-95": "無"
}

The reports come from feminist-perspective readings of each
song's lyrics; every item carries verbatim quotes and a
convergence mark, and the trailing 「僅單獨提及」 line of a
report holds the scattered findings of a single reading --
take them into account when inducing the patterns, but draw
the representative quotes from the main lists only.

Task: induce the patterns -- the recurring forms in which
the problems appear and operate -- across the reports.

Rules:

- A pattern describes how a problem works in the lyrics:
  what is coupled with what, who speaks, how the mechanism
  runs.  It is not a category for filing problems, and not
  every problem needs to belong to one; a pattern may also
  cut across several kinds of problems.
- Induce the patterns from the report contents; never
  introduce a problem or knowledge absent from the reports;
  the number of patterns follows the material, with nothing
  preset.
- For every pattern: a name, a paragraph describing the form
  and how it operates, and two or three representative
  quotes, each with its song ID.
- Describe and induce only; never evaluate severity, never
  make recommendations.

Output: Traditional Chinese (Taiwan usage).  One section per
pattern; output nothing else.

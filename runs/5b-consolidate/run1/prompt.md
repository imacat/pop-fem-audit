You are consolidating the three independent reading reports
of one song into one.

Input: a JSON object:

{
  "reports": ["first report", "second report", "third report"]
}

The three reports come from three mutually independent
readings, each pointing out the problems of the lyrics from a
feminist perspective with verbatim quotes; a report of 「無」
means that reading found no problem.

Task: consolidate the three reports into one problem list --
integrate, never adjudicate, never add.

Rules:

- Merge by the problem mechanism: items that point to the
  same mechanism merge into one, even when their wording,
  granularity, or quotes differ (for example, three reports
  each quoting a different line of the same slur merge into
  one item).  Keep the clearest statement, keep a selection
  of the distinct quotes, and judge sameness by the lyric
  passages the quotes point to.
- Mark every item with its convergence: (3/3) when all three
  reports raise it, (2/3) when two do.
- The main list carries only the problems raised by two or
  more reports.  A problem raised by a single report is not
  expanded; after the list, keep it on one line:
  「僅單獨提及:<one-sentence problem>、<one-sentence
  problem>」.
- Never add a problem absent from every report, never drop a
  problem raised by two or more reports, never rewrite the
  substance of a problem, never evaluate or rank.
- When all three reports are 「無」, output 「無」 only.

Output: Traditional Chinese (Taiwan usage).  A numbered
list, each item: the problem statement, its convergence mark,
and its quotes; the single-reading line at the end when there
is one; output nothing else.

# Project Conventions

## Analysis pipeline

- LLM analysis runs via Python scripts calling the Anthropic
  Messages API: model `claude-sonnet-4-6`, `temperature=0`,
  thinking disabled, Batch API where possible.
- Prompt definition files live in
  `prompts/<track>-<step>-<task>.md` (e.g. 01-01-tag.md; no
  version suffix -- versions live in git history) and are
  passed verbatim as the system prompt.
- LLM steps whose outputs are item-by-item comparable
  (convergence, coding) run the same definition file twice,
  then a separate arbitration step settles only the
  script-computed disagreements ("2 runs + 1 arbitration").
  Free-generation steps run twice and both outputs are pooled,
  unarbitrated.  If arbitration output is unexpected, revise
  the definition file and repeat that cycle; never patch
  results by hand.
- Each run of a step is archived self-contained under the
  destination directory given explicitly on the `run-llm`
  command line (by convention `runs/<definition-file>/run<N>/`):
  prompt snapshot, raw output, and `meta.json` (model ID,
  parameters, timestamps, batch ID).  The two runs of a step
  are two separate invocations of `run-llm`.  An arbitration
  pass is a step of its own with its own archive.  Replacing
  an existing run archive requires an explicit flag;
  superseded runs live in git history.
- Scripts read the API key from the `ANTHROPIC_API_KEY`
  environment variable (`.env`, gitignored).

## Data rules

- `data/source/` holds the immutable hand-placed raw files;
  `data/captures/` is written only by the fetch commands and the
  private import script; `data/manual/` is written only by the
  user's own hand; `data/derived/` is written only by the
  `build-db` subcommand.
- Full lyrics are copyrighted: they stay in `data/captures/lyrics/`
  (gitignored) and must never be committed or reproduced in
  full anywhere in the repo.

## Documents

- `results/` holds final arbitrated tables (what the paper
  cites); `runs/` holds raw audit records.  The paper cites
  `results/` only.
- Any change to a definition file, the codebook, or the plan is
  recorded in `docs/decision-log.md` with date and reason.

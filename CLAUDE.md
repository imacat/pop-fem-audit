# Project Conventions

## Analysis pipeline

- LLM analysis runs via Python scripts calling the Anthropic
  Messages API, Batch API where possible.  Steps 1 and 3 run
  on `claude-sonnet-4-6` with `temperature=0` and thinking
  disabled; steps 4 and 5 run on `claude-fable-5`, which
  accepts neither parameter -- step 4 absorbs its sampling
  variance by the majority vote, step 5 by consolidating the
  three readings.
- Prompt definition files live in
  `prompts/<step>-<substep>-<task>.md` (e.g. 01-tag.md; no
  version suffix -- versions live in git history) and are
  passed verbatim as the system prompt.  The number names a
  step of the research procedure, not the file: the
  deterministic vocabulary step (step 2) has no definition
  file yet holds its own number.  Zero padding is for
  sorting only -- prose says "step 1", "step 3".
- Itemwise LLM judgments (per-song coding in step 3,
  per-keyword group selection in step 4) run the same
  definition file three times, independently, over the same
  input; a deterministic tally then assigns an item (a
  (song, keyword) or (group, keyword) pair) when at least
  two of the three runs assign it ("3 runs + majority
  vote").  Free-generation steps run
  twice and both outputs are pooled.  The step-5 qualitative
  readings are neither: three independent readings per song,
  consolidated per song and synthesized across songs by
  their own definition files -- a qualitative protocol, not
  a vote (see docs/methodology.md).  The vocabulary is
  built by a deterministic subcommand (embedding +
  clustering), not by an LLM.  If a validation outcome is
  unexpected, revise the definition file and repeat that
  cycle; never patch results by hand.
- Each run of a step is archived self-contained under the
  destination directory given explicitly on the `run-llm`
  command line (by convention `runs/<step>/run<N>/`):
  prompt snapshot, raw output, and `meta.json` (model ID,
  parameters, timestamps, batch ID).  The runs of a step are
  that many separate invocations of `run-llm`.  Replacing
  an existing run archive requires an explicit flag;
  superseded runs live in git history.  Deterministic steps
  archive under `runs/<step>/` with no `run<N>` level.
- Token usage and cost of every `run-llm` execution are
  recorded in `docs/run-costs.md` in the same commit as the
  run archive.
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

- `results/` holds the final tallied tables (what the paper
  cites); `runs/` holds raw audit records.  The paper cites
  `results/` only.
- Any change to a definition file, the codebook, or the plan is
  recorded in `docs/decision-log.md` with date and reason.

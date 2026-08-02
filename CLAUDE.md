# Project Conventions

## Analysis pipeline

- LLM analysis runs via Python scripts calling the Anthropic
  Messages API: model `claude-sonnet-4-6`, `temperature=0`,
  thinking disabled, Batch API where possible.
- Prompt definition files live in `prompts/<task>_v<N>.md` and
  are passed verbatim as the system prompt.
- Every LLM step runs the same definition file twice, then a
  separate arbitration step reconciles the two outputs
  ("2 runs + 1 arbitration").  If arbitration output is
  unexpected, revise the definition file and repeat the whole
  cycle; never patch results by hand.
- Every execution is archived self-contained under
  `runs/<phase>/<date>-<prompt-version>/`: prompt snapshot,
  raw outputs of both runs, arbitration output, and `meta.json`
  (model ID, parameters, timestamps, batch IDs).
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
  recorded in `docs/decision_log.md` with date and reason.

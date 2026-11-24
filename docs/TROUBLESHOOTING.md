# Troubleshooting

English | [简体中文](./zh-CN/TROUBLESHOOTING.md)

Start with:

```bash
./bin/hydroweaver doctor --probe
./bin/hydroweaver tools --json
```

On Windows, use `npm run cli --` in place of `./bin/hydroweaver`.

## HydroWeaver installation

### Node is older than 24.15

Upgrade Node, reopen the shell, then run:

```bash
node --version
npm --version
npm ci
npm run setup
```

### `npm run setup` fails

Retry once after checking network access, free space, and write permission. If a
previous run was interrupted, remove generated dependencies/build output only
as directed by the first error, then rerun `npm ci && npm run setup`.

### CLI says the engine is not built

Run `npm run setup` from the repository root. The POSIX launcher requires
`engine/apps/hydroweaver/dist/cli.mjs`.

## Backend discovery

### `hydroweaver_backend` is not found

Use one of:

```bash
./bin/hydroweaver onboard --hydroweaver-repo /absolute/path/to/OpenAqua
export HYDROWEAVER_REPO=/absolute/path/to/OpenAqua
export HYDROWEAVER_COMMAND='["python","/path/to/adapter-compatible-cli.py"]'
```

A valid checkout contains `water_treatment_agent/requirements.txt`,
`water_treatment_agent/app/workflows/pipeline.py`, `test_openaqua.py`, and
`test_retrieval.py`.

### The wrong Python interpreter is selected

Set it explicitly:

```bash
export HYDROWEAVER_PYTHON=/path/to/OpenAqua/water_treatment_agent/.venv/bin/python
./bin/hydroweaver doctor --probe
```

On Windows, point to `.venv\Scripts\python.exe`.

### Probe reports missing `openai`, `rank_bm25`, or another package

Activate the OpenAqua environment and install its requirements:

```bash
cd /path/to/OpenAqua/water_treatment_agent
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Then make sure HydroWeaver resolves that interpreter with `HYDROWEAVER_PYTHON` or
the recognized virtual-environment location.

## Data and indexes

### Health reports `taxonomy_available: false` or missing knowledge directories

OpenAqua’s data are hosted on Hugging Face, not GitHub. Download and extract:

```bash
cd /path/to/OpenAqua/water_treatment_agent
python -m pip install -U huggingface_hub
hf download zhaorui-bi/OpenAqua data.zip WContBench/ \
  --repo-type dataset \
  --revision cc2d3c620e8ada7c62fa922cf3a827d8b42889e3 \
  --local-dir ../hf_openaqua
unzip ../hf_openaqua/data.zip -d .
```

The ZIP already contains `data/`; extracting it with `-d data` creates the
incorrect path `data/data/`. Verify that `data/unit-level/taxonomy.json`
exists.

### Indexes are missing or have zero chunks

First confirm that the unit-level TDB and optional case KB exist. Then ask the
agent to call `hydroweaver_build_indexes`. A zero-chunk build usually means data
were extracted to the wrong directory.

Expected generated files:

```text
water_treatment_agent/data/processed/indexes/corpus.jsonl
water_treatment_agent/data/processed/indexes/bm25_index.pkl
```

### Retrieval returns no evidence

Check, in order:

1. query normalization produced canonical contaminants;
2. taxonomy/data paths are available;
3. indexes exist and `chunk_count` is non-zero;
4. contaminant names match the downloaded taxonomy;
5. the result/log contains no index-unpickle or schema error.

## Models

### HydroWeaver says no model is configured

Run `./bin/hydroweaver onboard` or use `/provider` in the TUI. Provider credentials
for HydroWeaver are separate from `OPENROUTER_API_KEY`.

### OpenAqua does not parse a natural-language query

If `OPENROUTER_API_KEY` is absent, OpenAqua intentionally uses fallback logic
and does not extract all fields from free text. Supply structured fields or set
the key in the environment that launches HydroWeaver/Web/desktop process.

### Desktop does not see an environment variable

GUI apps launched from Finder/Start Menu often inherit a different environment.
Use a persistent OS-level variable, launch from a shell that exports it, or
store only the approved credential through your organization’s preferred
mechanism. Restart the desktop app after changing variables.

### Custom HydroWeaver provider fails HTTPS validation

Non-loopback endpoints must use HTTPS. Loopback HTTP remains allowed for local
servers such as `http://127.0.0.1:8000/v1`.

## Queries and constraints

### Contaminants disappear during normalization

They were not found in the controlled taxonomy. Run `hydroweaver_catalog` with a
search term and use the canonical or recognized synonym. Do not bypass taxonomy
validation by inventing an ID.

### Constraint checking rejects every candidate

Read the rule-level checks. Common causes include unknown unit names, drinking
water without disinfection, membrane separation when brine disposal is
unavailable, or an energy conflict. Auto-revision is limited and must be
reviewed; it is not a complete process redesign.

### The agent reports unsupported quantitative removal or compliance claims

Treat that as an interpretation error. Ask it to distinguish retrieved evidence
from inference, cite the exact chunk, and remove claims that the source does not
support.

### The optimization loop ends `stalled` or `budget_exhausted`

The critic and the planner both stopped making progress, or the round budget was
spent, before every chain passed. Read the last round's `unresolved` list: it
names the failing chains, their statuses, and their violations. Then either amend
the case (declare the missing constraint, or relax a conflicting one) and rerun,
or raise `maxRounds`/`maxJobs` for a separately authorized run. A stalled loop is
a screening boundary, not a failure to hide; it never becomes a feasible result.

## Jobs

### A long operation appears lost

```text
hydroweaver_job_list → hydroweaver_job_status → hydroweaver_job_manifest
```

Then read a bounded log tail or `view: "errors"`. New jobs are stored under
`<HYDROWEAVER_WORKDIR>/hydroweaver-jobs` (or `<cwd>/hydroweaver-jobs` when no workdir is
set). The CLI and MCP also search the current process's `<cwd>/hydroweaver-jobs`
for older MCP jobs and keep those jobs in place. A different historical launch
directory cannot be discovered automatically: set `HYDROWEAVER_JOBS_DIR` to its
`hydroweaver-jobs` directory to access it. An explicit `HYDROWEAVER_JOBS_DIR` selects
only that store. If the same ID occurs in both default stores, select the
intended store explicitly rather than moving or overwriting either record.

### A job succeeded but no artifact is listed

`hydroweaver_job_artifacts` only indexes the explicit `--output` location. Check
`configuredOutput` in job status/manifest and inspect the bounded log for a
backend-reported path.

### Cancellation refuses a stale job record

This is a safety feature: HydroWeaver verifies that the recorded process still
matches the expected runner before signalling it. Inspect the job state and
remove stale metadata only after confirming no related process remains.

## Web and desktop

### Web UI does not open

Copy the complete `Local:` URL printed by `hydroweaver web`; it includes an
authentication token in the fragment. Try another port with `--port 8765` and
check loopback firewall/proxy rules.

### Desktop reports startup timeout or engine exit

Run `npm start` from a terminal to retain logs, select **文件 → 重启引擎**, and
rebuild with `npm run setup` if files are stale. Use `HYDROWEAVER_DEBUG=1 npm start`
for developer tools.

## Logs and privacy

HydroWeaver configuration lives under `~/.hydroweaver`. Development desktop state
lives under `hydroweaver-data/`; jobs live under the configured workspace. These
locations can contain prompts, source-water data, paths, model output, and
credentials. Redact them before sharing.

## Still stuck

Open an issue at <https://github.com/zhaorui-bi/HydroWeaver/issues> with:

- redacted `hydroweaver doctor --json`;
- OS, Node, npm, Python, and OpenAqua commit;
- `hydroweaver_status` output;
- the smallest query/input that reproduces the issue;
- bounded error-log excerpts.

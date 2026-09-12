# Semantic contract implementation and evaluation

The first executable implementation of `nba_semantics/0.1` is available on
`codex/semantic-contract-evals`. It includes a metric contract, deterministic
calculations, bounded warehouse capture, natural-language planning, and independent
evaluations. The local BigQuery-backed Ask JSON and streaming routes now use this
contract for governed metric queries. No new physical tables were created. These
changes have not been deployed; legacy metric presentation metadata uses the governed formulas and directions.

The [original proposal](semantic-contract-v0.1.md) remains the design reference.
Passing this bounded suite does not satisfy every proposed production release gate.

## Implementation

| File | Responsibility |
| --- | --- |
| `app/agent/semantic_contract.yml` | Versioned definitions for 16 metrics |
| `app/agent/semantics.py` | Scope validation, aggregation, qualification, ranking, percentiles, comparisons, identity and injury ordering |
| `app/agent/semantic_source.py` | Fixed, parameterized BigQuery capture with byte/row limits, snapshot identity and completeness checks |
| `app/agent/semantic_planner.py` | Source-backed identity references, constrained plans and deterministic execution |
| `app/agent/semantic_serving.py` | Bounded snapshot cache and source-backed player discovery |
| `app/agent/semantic_answer.py` | Ask response rendering, clarification and conversation integration |
| `scripts/evaluate_semantics.py` | Synthetic calculation and evidence cases |
| `scripts/evaluate_historical_semantics.py` | Independently authored SQL references over frozen historical rows |
| `scripts/evaluate_semantic_language.py` | Live planner, paraphrase and repeated ambiguity evaluations |
| `scripts/evaluate_semantic_injuries.py` | Historical injury evidence and unverified-time checks |

The runner uses ratio-of-sums shooting percentages, explicit season/phase/window
scope, historical appearance-team filters, and separate simple/weighted fantasy
formulas. Ranking defaults to five games as project policy; shooting rankings
require an attempt threshold. Null components remain unknown, incomplete samples
are excluded from rankings, singleton percentiles are unavailable, and ties share
rank. Comparison evidence discloses overlap and percentage-point versus relative
change. No count threshold limits identity discovery.

The model receives validated player references and available team labels. It
cannot invent IDs or execute SQL. Query count is enforced by schema: one summary,
two comparison queries, or zero for withheld requests. Ambiguous names and missing shooting qualification clarify deterministically.
Unspecified Fantasy Score defaults to `fantasy_proxy_weighted`; explicit simple
scoring remains distinct.
Explicit ISO date ranges bind both endpoints; numeric day windows bind their count.
The runner validates model plans before calculating any answer.

## Current evidence

| Evaluation | Result | What it establishes |
| --- | --- | --- |
| Synthetic cases | 24/24 pass | Representative subsets of proposal families E01–E24 |
| Historical SQL checks | 20/20 pass | Phase, identity, trade, ratios, cohort, membership and comparison checks across both historical seasons |
| Historical injury cases | 2/2 pass | Ambiguous archive times produce unverified ordering |
| Language suite, latest run | 60/60 pass | 14 families, three phrasings each, with repeated ambiguity/policy requests |
| Python regression suite | 483 pass, 1 skip | Local implementation and regression tests |

Lint, formatting and static typing pass. The language run used the configured
`gpt-5.4-mini`: 42 actual model calls and 18 deterministic results. It exercised synthetic evidence
through `StatsAgent.answer` with `--ask`, including deterministic response rendering.
A live browser request against BigQuery returned Nikola Jokić’s 2024–25 regular-season
weighted Fantasy Score as 66.3 over 70 valid games, with formula and provenance.
An independent formula calculation over the frozen snapshot matched (66.2771).
This is a local integration check, not deployment validation.
The grader checks typed results, population, scope and required evidence rather
than matching answer wording. SQL expectations do not use production aggregation
helpers. Tests also inject wrong expectations and verify that the graders fail.

The historical fact snapshot contains 56,196 rows. One read scanned 10,673,558
bytes (20,971,520 billed), under a 100 MB cap; capture latency was 10,982 ms. This
is capture cost, not interactive serving latency. Both seasons and phases were
read at one BigQuery system timestamp. Completeness checks establish full retrieval
of warehouse rows, not independent completeness of upstream NBA observations.

The injury snapshot contains 37,968 silver rows. Gold drops matchup and scheduled
game time; silver preserves them. Captured times such as `07:30 (ET)` lack AM/PM.
The two historical checks therefore expect **tipoff unverified**. They do not
establish actual pregame ordering. Source publication time is not ingestion time;
corrected historical facts do not reconstruct what was known at an earlier date.

All previous live runs remain in ignored local reports, including failures and a
harness argument-binding error with explicitly corrected zero-call accounting.
The latest passing run does not erase earlier failures or establish stability
outside these cases. Expected results remain `human_reviewed: false`, and reports
retain `release_ready: false`.

## Reproduce

Offline synthetic checks run in CI, which uploads the JSON report:

```bash
python scripts/evaluate_semantics.py --output reports/semantic-layer/evaluation.json
python -m pytest tests/test_semantic_contract.py tests/test_semantic_source.py tests/test_semantic_planner.py tests/test_semantic_injury_evaluation.py -q
```

Capture facts once, then freeze independent reference SQL results. Omit `--freeze`
on subsequent evaluations to reuse the exact expected answers:

```bash
python scripts/capture_semantic_snapshot.py --project YOUR_PROJECT \
  --seasons 2023-24 2024-25 --output reports/semantic-layer/historical-snapshot.json
python scripts/evaluate_historical_semantics.py \
  --snapshot reports/semantic-layer/historical-snapshot.json \
  --references reports/semantic-layer/historical-references.json --freeze \
  --output reports/semantic-layer/historical-evaluation.json
```

Live model evaluation is opt-in and uses existing app settings:

```bash
python scripts/evaluate_semantic_language.py --ask --env-file /path/to/local/.env \
  --output reports/semantic-layer/language-evaluation-new.json
```

Capture injury evidence once; omit `--project` to reevaluate the saved snapshot:

```bash
python scripts/evaluate_semantic_injuries.py --project YOUR_PROJECT \
  --snapshot reports/semantic-layer/injury-snapshot.json \
  --output reports/semantic-layer/injury-evaluation.json
```

Capture and reference creation refuse to overwrite frozen files. Reports and source
rows remain in ignored `reports/`; warehouse data and credentials are not committed.
The planner uses [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
with independent application validation.

## Migration scope

BigQuery-backed Ask supports metric summaries, rankings, percentiles, two-query
comparisons, and single-player metric game logs with appearance charts. JSON and SSE preserve the selected season, including historical
conversation storage. Unsupported operations return a structured unsupported result;
there is no fallback from a failed governed query to arbitrary SQL. Similarity requests and explicit league-average/baseline comparisons retain their
legacy routes, including pending player clarification. They do not claim governed
semantic evidence. Injury answers remain outside this governed slice. Rolling averages, cumulative charts and multi-metric game logs remain unsupported.

Game logs reuse the same phase, date, appearance-window, team and opponent filters.
Rows are chronological; a display cap keeps the latest requested observations and
explicitly reports displayed versus observed counts. Per-game shooting ratios use
that game's components and do not require ranking thresholds. Missing values stay
unavailable in the table; charts are withheld if any displayed game is unavailable.
The line-chart scale includes negative values such as plus/minus. No interpolation,
rolling calculation or cumulative total is implied.

Stage-two language evidence is saved in `reports/semantic-layer/game-log-evaluation-v1.json`;
all 60 cases passed through Ask, including six new game-log/ratio phrasings. Ten new
Python cases cover windows, ratios, display limits, identity, qualification, team
scope, rendering and unknown values. The JavaScript regression suite also verifies
that negative values stay inside the chart area. A live historical browser check
rendered Jokić’s last five 2024–25 regular-season weighted scores as 64.9, 86.5,
61.9, 66.7 and 47.9; independent calculations from frozen rows matched all five.

The cache retains at most three season scopes per repository, with the configured
agent cache TTL. Each capture enforces a 100 MB scan cap and 100,000-row maximum,
then validates completeness before caching. This reads a complete bounded season
scope, not a new serving table; cold-request latency still needs measurement.

## Before production release

- Review metric definitions and independently authored historical expectations.
- Extend language coverage to remaining proposal families and realistic historical
  question variants; the current language suite covers 14 families, not all 24.
- Obtain verified game-start timestamps before claiming historical pregame ordering.
- Migrate preserved legacy similarity and league-baseline workflows before claiming
  complete governed coverage.
- Validate the Anthropic provider with live requests; this run used OpenAI only.
- Measure bounded serving cost and latency before considering new serving tables.

## PR review corrections

Shared explicit ranges, trailing-day windows and combined phases apply to both
comparison queries. Distinct explicit comparison windows return clarification
instead of silently overwriting either side. Slash-form dates are excluded from
season extraction while slash-separated season tokens remain supported.

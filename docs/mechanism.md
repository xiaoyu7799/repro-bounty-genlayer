# ReproBounty mechanism

## Goal

A research result is only as good as its replication. A poster locks a
bounty (simulated mGEN ledger units) behind a published experiment spec;
a reproducer re-runs the code, submits the run log and the actual output
text; validator consensus decides whether the replication genuinely
reproduced the claimed result. The bounty is released only on a
`REPRODUCED` verdict. A failed replication keeps the bounty locked for
the next attempt; an inconclusive one does the same.

## State

- `bounties: TreeMap[u256, str]` — one JSON record per bounty.
- `attempts: TreeMap[u256, str]` — one JSON record per replication attempt.
- `balances: TreeMap[str, u256]` — simulated mGEN ledger balances.
- `claimed_demo: TreeMap[str, u256]` — 1 if the address already claimed
  demo funds, else absent.
- `reputation: TreeMap[str, u256]` — reproducer/challenger reputation.
  Any address starts at 100 on first participation.
- `next_bounty_id`, `next_attempt_id: u256` — counters from 0.

A bounty:

```json
{
  "id": 0,
  "poster": "0x…",
  "spec_hash": "<64 lowercase hex>",
  "code_ref": "https://…/reproduce.py",
  "expected_code_hash": "<64 lowercase hex>",
  "expected_output_hash": "<64 lowercase hex>",
  "amount": 4000,
  "escrow": 4000,
  "status": "OPEN",
  "winner": null
}
```

An attempt:

```json
{
  "id": 0,
  "bounty_id": 0,
  "reproducer": "0x…",
  "code_hash": "<64 lowercase hex>",
  "output_text": "pi=3.14159",
  "output_hash": "<sha256(output_text), computed on-chain>",
  "run_log": "REPRO-START … REPRO-END …",
  "status": "SUBMITTED",
  "round": 0,
  "pending_verdict": null,
  "verdict": null,
  "first_verdict": null,
  "scores": null,
  "challenged": false,
  "challenger": null,
  "witness": null
}
```

Statuses: bounty `OPEN` / `CLOSED` / `CANCELLED`; attempt `SUBMITTED` /
`EVALUATING` / `FINALIZED`.

## Money: simulated mGEN ledger only

All bounty money is a ledger inside the contract, in simulated mGEN
units. `claim_demo_funds` credits 10000 once per address. Posting a
bounty deducts the amount from the poster's ledger balance into escrow.
A `REPRODUCED` finalization moves the escrow to the reproducer's ledger
balance. A `FAILED` or `INCONCLUSIVE` finalization leaves the escrow
locked in the bounty so a later attempt can still win it. The poster may
cancel an `OPEN` bounty with no attempt currently `EVALUATING`; the
escrow returns to the poster's ledger balance. No real GEN ever moves.

Amounts must be positive even integers, so any even split is exact.

## Deterministic checks (exact, no tolerance anywhere)

These run in deterministic code, identically for every validator:

1. `output_hash = pure_sha256_hex(output_text)`, computed on-chain from
   the submitted text at submit time — never trusted from the submitter.
   `hash_match` is exact string equality with `expected_output_hash`.
   A one-bit difference in the output produces a completely different
   hash, so there is no "close enough" case. A different-but-close
   output hash is `FAILED`.
2. `code_match` is exact string equality between the submitted
   `code_hash` and the bounty's `expected_code_hash`.
3. `log_complete` is exact: the run log contains both literal markers
   `REPRO-START` and `REPRO-END` and is at least 40 characters long.
   A missing log, a log without the end marker, or a truncated log is
   not complete.

The deterministic pre-verdict `D`:

| condition | `D` |
|---|---|
| not `hash_match` | `FAILED` |
| `hash_match`, not `code_match` | `FAILED` |
| both match, not `log_complete` | `INCONCLUSIVE` |
| all three hold | `REPRODUCED_CANDIDATE` |

## LLM judgement (subjective part only)

The LLM scores only whether the log reads as a genuine run of the
claimed code producing the submitted output — three integer dimensions
0–100: `log_consistency`, `output_plausibility`, `code_fidelity`.
It never decides the hash, the code, or the log markers; those are
already decided deterministically above.

The prompt instructs decisive scoring: clearly genuine evidence scores
85–100, anything doubtful scores 0–59, and no score may fall in 60–80.

Let `m = min(three scores)`. The verdict from scores, `L`:

- `m >= 81` → `REPRODUCED`
- `m <= 59` → `INCONCLUSIVE`
- `60 <= m <= 80` → dead zone: the leader result is rejected by every
  validator, no verdict is written, the attempt stays `SUBMITTED` and
  the evaluation can be retried.

The final verdict `V` combines `D` and `L`:

- `D = FAILED` → `V = FAILED` (scores cannot rescue a hash/code
  mismatch; if `L = REPRODUCED` anyway, the scores are kept as a
  contradiction witness on the attempt record).
- `D = INCONCLUSIVE` → `V = INCONCLUSIVE`.
- `D = REPRODUCED_CANDIDATE` → `V = L`.

## Worst-case spread calculation (the DualRate test)

Score tolerance in `validate`: each validator accepts the leader's
scores only if `|leader_score − own_score| <= 10` on every dimension.
Each validator runs the same judgement independently, so the validator's
own `m` differs from the leader's `m` by at most 10
(`|Δm| <= 10`, since each of the three scores moves by at most 10).

The only verdict boundary is `m = 70` (below it `INCONCLUSIVE`, at or
above it `REPRODUCED`). Accepted leader values sit at least 11 away
from that boundary on both sides:

| leader `m` | validator's own `m` range | band of every compatible `m` | verdict |
|---|---|---|---|
| 81 (lowest accepted `REPRODUCED`) | 71–91 | all `>= 70` | `REPRODUCED` |
| 100 (highest) | 90–100 | all `>= 70` | `REPRODUCED` |
| 59 (highest accepted `INCONCLUSIVE`) | 49–69 | all `< 70` | `INCONCLUSIVE` |
| 0 (lowest) | 0–10 | all `< 70` | `INCONCLUSIVE` |
| 60–80 (dead zone) | — | rejected, nothing written | no verdict |

The deterministic part (`D`) is exact string equality and exact
substring checks, identical for every validator, so it cannot differ
between two compatible leader outputs at all.

**Worst-case spread: 0 verdict flips, 0 mGEN difference in escrow
movement, between any two validator-compatible leader outputs.** The
only quantity that can vary between validators is the LLM scores, and
the margin rule confines that variation inside a single verdict band.
There is no tolerance band that lets two different conclusions both
pass: a hash that differs by one character is `FAILED`, a log missing
its end marker is `INCONCLUSIVE` at best, and a score set sitting near
the boundary is rejected outright instead of being averaged into a
verdict.

Edge cases, covered by the same rules (not by happy-path only):

- Missing log: `submit_replication` rejects an empty log; a log
  without `REPRO-END` gives `log_complete = false` → `D` is at best
  `INCONCLUSIVE`, never `REPRODUCED`.
- Truncated output: any truncation changes the SHA-256 completely →
  `hash_match = false` → `FAILED`.
- Different-but-close output hash: there is no distance metric on
  hashes anywhere in the contract; equality is exact, so "close"
  is `FAILED`.
- Leader scores 75/90/90 (`m = 75`, dead zone): rejected by
  `validate`, nothing written, attempt stays `SUBMITTED`.
- Leader scores 81/82/83 vs validator scores 71/72/73 (each within
  10): both `m` values are on the `REPRODUCED` side of 70 → same
  verdict `REPRODUCED`.

## Flow

1. `claim_demo_funds()` — once per address, +10000 simulated mGEN.
2. `post_bounty(spec_hash, code_ref, expected_code_hash,
   expected_output_hash, amount)` — amount must be a positive even
   integer and not exceed the poster's ledger balance; the amount
   moves into escrow. Returns the bounty id.
3. `submit_replication(bounty_id, code_hash, output_text, run_log)` —
   bounty must be `OPEN`; the contract computes `output_hash` from
   `output_text` with pure-Python SHA-256. Returns the attempt id.
4. `evaluate_replication(attempt_id)` — round 1: leader and every
   validator independently recompute `D` and run the LLM judgement;
   `validate` enforces exact `D` agreement, per-score tolerance 10,
   and the dead-zone rule. On agreement the attempt becomes
   `EVALUATING` with a pending verdict and round 1 recorded.
5. `challenge_replication(attempt_id)` — deterministic; only while
   `EVALUATING`, round 1, not already challenged, and not by the
   reproducer. Records the challenger.
6. `evaluate_replication(attempt_id)` — round 2 (only after a
   challenge): a fresh independent judgement; this round finalizes
   directly with the second verdict. The first verdict is retained
   as `first_verdict` on the record.
7. `finalize_replication(attempt_id)` — permissionless, anyone may
   call; only while `EVALUATING`, round 1, not challenged. Applies
   the pending verdict.
8. `cancel_bounty(bounty_id)` — poster only, bounty `OPEN`, no
   attempt `EVALUATING`; escrow returns to the poster.

## Consequences of a FINALIZED verdict

- `REPRODUCED`: escrow moves to the reproducer's ledger balance,
  bounty becomes `CLOSED`, winner is recorded, reproducer
  reputation +10.
- `FAILED`: escrow stays locked in the bounty (a later attempt can
  still win it), bounty stays `OPEN`, reproducer reputation −5.
- `INCONCLUSIVE`: escrow stays locked, bounty stays `OPEN`, no
  reputation change.
- Challenge resolution (round 2 only): if the second verdict equals
  the first, the challenge failed and the challenger loses 5
  reputation; if it differs, the challenge succeeded and the
  challenger gains 5 reputation. The first verdict is kept on the
  record; the second verdict is the active one.

## Finality and contradictions

A `FINALIZED` verdict is immutable: `evaluate_replication` and
`finalize_replication` both reject a `FINALIZED` attempt. A later
claim that contradicts a finalized verdict is never written over it;
a disagreement between the deterministic check and the LLM scores
(e.g. scores say `REPRODUCED` while the output hash mismatches) is
kept as a `witness` object on the attempt record, with the
deterministic verdict standing.

## Pure-Python SHA-256

The contract does not rely on `hashlib` being available in GenVM: it
carries a pure-Python SHA-256 implementation, verified locally against
the standard library on test vectors (empty string, short ASCII,
multi-block input) before deployment. All numbers crossing the
nondeterministic boundary are integers or strings; no floats are used
anywhere.

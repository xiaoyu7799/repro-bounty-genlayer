# ReproBounty

A research-replication bounty primitive for GenLayer: a poster locks a bounty behind a published experiment spec, a reproducer re-runs the code and submits the run log plus the actual output text, and validator consensus decides whether the replication genuinely reproduced the claimed result — `REPRODUCED` / `FAILED` / `INCONCLUSIVE`. The bounty is released only on `REPRODUCED`.

- Contract: [0x30e04052D3968E21f74FcB6cC4bBEFa9CC527472](https://explorer-studio.genlayer.com/address/0x30e04052D3968E21f74FcB6cC4bBEFa9CC527472)
- Network: Stable Studionet only (Chain ID 61999, RPC https://studio.genlayer.com/api)
- Repository: https://github.com/xiaoyu7799/repro-bounty-genlayer
- Evidence: [evidence.json](https://github.com/xiaoyu7799/repro-bounty-genlayer/blob/main/evidence.json) (links + values only)

All bounty money is a simulated mGEN ledger inside the contract. `claim_demo_funds` credits 10000 simulated mGEN once per address; posting a bounty deducts from that balance into escrow; a `REPRODUCED` finalization moves the escrow to the reproducer. No real GEN ever moves.

## How the verdict is decided

The decision has two layers, and the deterministic layer always wins:

1. **Deterministic, exact.** The output hash is computed on-chain from the submitted text with pure-Python SHA-256 and must equal the expected hash exactly. The code hash must match exactly. The run log must contain both `REPRO-START` and `REPRO-END` markers and be at least 40 characters. There is no tolerance and no "close enough": a different-but-close output hash is `FAILED`; a log missing its end marker is `INCONCLUSIVE` at best.
2. **LLM judgement, subjective part only.** The LLM scores the log's credibility on three integer dimensions 0–100 (`log_consistency`, `output_plausibility`, `code_fidelity`). The verdict comes from the minimum score with a single boundary at 70 and a required margin of 11: accepted leader minima are `>= 81` (`REPRODUCED`) or `<= 59` (`INCONCLUSIVE`); 60–80 is a dead zone that validators reject outright, so the attempt stays `SUBMITTED` and can be retried. Per-score tolerance is 10, so any validator-compatible score set stays on the same side of the boundary. Worst-case spread between two validator-compatible leader outputs: **0 verdict flips, 0 mGEN difference**. See [docs/mechanism.md](docs/mechanism.md) for the full calculation, including the edge cases.

Flow: `claim_demo_funds` → `post_bounty` → `submit_replication` → `evaluate_replication` (round 1, `EVALUATING` with a pending verdict) → optionally `challenge_replication` (only while `EVALUATING`, before finalize) → `evaluate_replication` again (round 2, finalizes directly) or `finalize_replication` (permissionless, anyone may call, only when unchallenged). A `FINALIZED` verdict is immutable; a disagreement between the deterministic check and the LLM scores is kept as a `witness` on the attempt record. Amounts must be positive even integers. Reputation starts at 100 on first participation: +10 for a `REPRODUCED` replication, −5 for `FAILED`; a failed challenge (second verdict equals the first) costs the challenger 5, a successful one gains 5.

## Contract

- Source: [contracts/repro_bounty.py](contracts/repro_bounty.py)
- SHA-256: `b61d458139954acb829ff88b1eaa9aa7431391ae1f5f2482805be674759960d8` (matches the deployed code, verified by reading the deployed code back via RPC)
- Deploy tx: [0x98fbfabf8a975ff2d7f20b48e14b02b633d3c8d39f21e300901d0ea3b2c990d3](https://explorer-studio.genlayer.com/address/0x30e04052D3968E21f74FcB6cC4bBEFa9CC527472) — FINALIZED, MAJORITY_AGREE
- Deployment manifest: [deployment.json](deployment.json)

## Verified on-chain flow

Two bounties, two attempts, all 10 flow transactions FINALIZED with MAJORITY_AGREE (plus the deploy transaction = 11 total). Full receipts and read-backs: [docs/live-verification.md](docs/live-verification.md).

| step | result (read back via RPC) |
|---|---|
| Bounty #0, 4000 simulated mGEN | posted by `0x355a…2400` |
| Attempt #0, output `pi=3.14159` | output hash `759ba5bc…eb1bb` == expected, exactly |
| Evaluate #0 round 1 | `EVALUATING`, pending `REPRODUCED`, scores 95/90/85 (min 85) |
| Challenge #0 | recorded, challenger `0xD9eD…6126` |
| Evaluate #0 round 2 | `FINALIZED`, `REPRODUCED`; bounty #0 `CLOSED`, escrow 0, winner paid 4000 |
| Bounty #1, 2000 simulated mGEN | posted |
| Attempt #1, output `pi=3.14000` | output hash `e49f7771…fb88b1` != expected → `FAILED` |
| Evaluate #1 round 1 | `EVALUATING`, pending `FAILED`; LLM itself scored `output_plausibility` 12 |
| Finalize #1 | `FINALIZED`, `FAILED`; bounty #1 stays `OPEN`, escrow 2000 locked |

Final ledger state: reproducer balance 4000, poster balance 4000, reproducer reputation 105 (100 +10 −5), challenger reputation 95 (challenge failed: both rounds agreed `REPRODUCED`).

## Usage

Contract-only: no app frontend. Call it with `genlayer-js` 1.1.8 or any Studionet client. Scripts in this repo:

```bash
npm install
node scripts/deploy.mjs    # deploy to Studionet (ephemeral key if none supplied)
node scripts/flow.mjs      # full on-chain flow (10 txs), writes evidence.json
node scripts/verify.mjs    # independent re-check of every receipt + read-back
node scripts/simulate.mjs  # local mock of the decision rules (mock only, not consensus evidence)
python3 tests/test_local.py  # local mock tests, 62 checks (mock only)
```

### Call examples

All hashes below are SHA-256 hex of the demo inputs (recompute them; do not trust the strings):

```js
// Demo inputs (verified in tests/test_local.py against hashlib):
//   sha256("spec: compute pi to 5 decimals") = 9e0c088d4a4a58300e808f44646d87a9708057a98872de00eabb842be16f8e1f
//   sha256("reproduce.py v1")               = 3f9c3016763ca5b506de216152903050c37080f9bbce666d6c934207434dbeda
//   sha256("pi=3.14159")                    = 759ba5bc0ba9d4a301ef865bd4bbe968c8dec6a93b899912e8225bcd8f6eb1bb

// 1. Claim 10000 simulated mGEN (once per address).
await client.writeContract({ address, functionName: "claim_demo_funds", args: [], value: 0n });

// 2. Post a bounty of 4000 simulated mGEN (positive even integer).
await client.writeContract({
  address, functionName: "post_bounty", value: 0n,
  args: ["9e0c088d4a4a58300e808f44646d87a9708057a98872de00eabb842be16f8e1f",
         "https://example.org/reproduce.py",
         "3f9c3016763ca5b506de216152903050c37080f9bbce666d6c934207434dbeda",
         "759ba5bc0ba9d4a301ef865bd4bbe968c8dec6a93b899912e8225bcd8f6eb1bb", 4000n],
});

// 3. Submit a replication: code hash, output text, run log with both markers.
await client.writeContract({
  address, functionName: "submit_replication", value: 0n,
  args: [0n, "3f9c3016763ca5b506de216152903050c37080f9bbce666d6c934207434dbeda",
         "pi=3.14159",
         "REPRO-START run reproduce.py --seed 7\nstep 1: load data ok\nstep 2: compute pi series ok\nRESULT pi=3.14159 matches expected\nREPRO-END exit 0"],
});

// 4. Evaluate (round 1), then finalize (permissionless) or challenge + re-evaluate.
await client.writeContract({ address, functionName: "evaluate_replication", args: [0n], value: 0n });
await client.writeContract({ address, functionName: "finalize_replication", args: [0n], value: 0n });

// 5. Read back.
await client.readContract({ address, functionName: "get_attempt", args: [0n] });
await client.readContract({ address, functionName: "get_bounty", args: [0n] });
await client.readContract({ address, functionName: "get_balance", args: ["0x…"] });
await client.readContract({ address, functionName: "get_reputation", args: ["0x…"] });
```

### Method reference

| method | type | notes |
|---|---|---|
| `claim_demo_funds()` | write | +10000 simulated mGEN, once per address |
| `post_bounty(spec_hash, code_ref, expected_code_hash, expected_output_hash, amount)` | write | amount: positive even integer, ≤ balance; returns bounty id |
| `submit_replication(bounty_id, code_hash, output_text, run_log)` | write | bounty must be `OPEN`; returns attempt id |
| `evaluate_replication(attempt_id)` | write | round 1 → `EVALUATING`; round 2 after challenge → `FINALIZED` |
| `challenge_replication(attempt_id)` | write | only while `EVALUATING`, round 1, not by the reproducer |
| `finalize_replication(attempt_id)` | write | permissionless; only when `EVALUATING`, round 1, unchallenged |
| `cancel_bounty(bounty_id)` | write | poster only, bounty `OPEN`, no attempt `EVALUATING`; escrow refunded |
| `get_bounty(id)` / `get_attempt(id)` / `list_bounties(offset, limit)` / `list_attempts(offset, limit)` | view | JSON records |
| `get_bounty_count()` / `get_attempt_count()` | view | `u256` |
| `get_balance(address)` / `get_reputation(address)` | view | simulated mGEN balance; reputation (starts at 100) |

## Documentation

- [docs/mechanism.md](docs/mechanism.md) — state, deterministic rules, LLM scoring, worst-case spread calculation
- [docs/live-verification.md](docs/live-verification.md) — every core transaction receipt + read-back
- [docs/REVIEWER.md](docs/REVIEWER.md) — reviewer fast path: where to start, shortest recheck steps
- [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) — limits, in neutral terms
- [deployment.json](deployment.json) — network, contract address, deploy tx, source SHA-256
- [evidence.json](evidence.json) — links + values only

## Tests

- `python3 tests/test_local.py` — 62 local mock checks: pure-Python SHA-256 vs `hashlib` test vectors, the deterministic verdict table, exhaustive score-band margin proof (1570 leader/validator pairs in `scripts/simulate.mjs`), the combine-verdict table, and a full state-machine simulation with canned LLM scores (including the dead-zone rejection and the challenge path). Local mocks only — they prove the rules are satisfiable and the margins hold; only the on-chain `evaluate_replication` transactions are consensus evidence.

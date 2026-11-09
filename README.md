# ReproBounty

A research-replication bounty primitive for GenLayer: a poster locks a bounty in real testnet GEN behind a published experiment spec, a reproducer re-runs the code and submits the run log plus the actual output text, and validator consensus decides whether the replication genuinely reproduced the claimed result — `REPRODUCED` / `FAILED` / `INCONCLUSIVE`. Payouts are pull payments only: finalization records a credit in wei, and the beneficiary calls `withdraw_payout()` to receive real GEN.

- Contract: [0xFC225789B5322eE883b7FE96cf0353caB5C938c9](https://explorer-studio.genlayer.com/address/0xFC225789B5322eE883b7FE96cf0353caB5C938c9)
- Network: Stable Studionet only (Chain ID 61999, RPC https://studio.genlayer.com/api)
- Repository: https://github.com/xiaoyu7799/repro-bounty-genlayer
- Evidence: [evidence.json](https://github.com/xiaoyu7799/repro-bounty-genlayer/blob/main/evidence.json) (links + values only)

All bounty money is real testnet GEN (1 GEN = 10^18 wei, faucet-funded, zero cash cost). `post_bounty` is payable: the GEN sent with the call is the bounty and is locked in the contract. `REPRODUCED` credits the full escrow to the reproducer; `FAILED` credits it back to the poster; `INCONCLUSIVE` splits it 25% to the reproducer and 75% back to the poster. No push payment ever happens at finalization time.

## How the verdict is decided

The decision has two layers, and the deterministic layer always wins:

1. **Deterministic, exact.** The output hash is computed on-chain from the submitted text with pure-Python SHA-256 and must equal the expected hash exactly. The code hash must match exactly. The run log must contain both `REPRO-START` and `REPRO-END` markers and be at least 40 characters. There is no tolerance and no "close enough": a different-but-close output hash is `FAILED`; a log missing its end marker is `INCONCLUSIVE` at best.
2. **LLM judgement, subjective part only.** The LLM scores the log's credibility on three integer dimensions 0–100 (`log_consistency`, `output_plausibility`, `code_fidelity`). The verdict comes from the minimum score with a single boundary at 70 and a required margin of 11: accepted leader minima are `>= 81` (`REPRODUCED`) or `<= 59` (`INCONCLUSIVE`); 60–80 is a dead zone that validators reject outright, so the attempt stays `SUBMITTED` and can be retried. Per-score tolerance is 10, so any validator-compatible score set stays on the same side of the boundary. Worst-case spread between two validator-compatible leader outputs: **0 verdict flips, 0 GEN difference**. See [docs/mechanism.md](docs/mechanism.md) for the full calculation, including the edge cases.

Flow: `post_bounty` (payable, 40 GEN) → `submit_reproduction` → `evaluate_reproduction` (round 1, `AWAITING_DECISION` with a pending verdict) → optionally `challenge_reproduction` (only while `AWAITING_DECISION`, before finalize; costs reputation, not GEN) → `evaluate_reproduction` again (round 2, finalizes directly) or `finalize_reproduction` (permissionless, anyone may call, only when unchallenged) → `withdraw_payout` (pull the GEN). A `DECIDED` verdict is immutable; a disagreement between the deterministic check and the LLM scores is kept as a `witness` on the attempt record. Bounties must be divisible by 4 wei so the 25% / 75% split is exact. Reputation starts at 0: +10 for a `REPRODUCED` replication, −5 for `FAILED` (floored at 0); a failed challenge (second verdict equals the first) costs the challenger 5, a successful one gains 5.

## Contract

- Source: [contracts/repro_bounty.py](contracts/repro_bounty.py)
- SHA-256: `dfb7a6719c249c2aeaf58d7e9100ff64e4a005c6676032c19e760b718efae770` (matches the deployed code, verified by reading the deployed code back via RPC and hashing the decoded bytes)
- Deploy tx: [0xae0d289f30a41e808c819cb8fe5f31ffed40f8c27795dad51a3df94de8457f45](https://explorer-studio.genlayer.com/address/0xFC225789B5322eE883b7FE96cf0353caB5C938c9) — FINALIZED, MAJORITY_AGREE
- Deployment manifest: [deployment.json](deployment.json)

## Verified on-chain flow

Four bounties, three attempts, all 20 flow transactions FINALIZED with MAJORITY_AGREE (plus the deploy transaction = 21 total). Full receipts and read-backs: [docs/live-verification.md](docs/live-verification.md).

| step | result (read back via RPC) |
|---|---|
| Bounty #0, 40 GEN | posted by `0xaD44…2ac9` |
| Attempt #0, output `pi=3.14159` | output hash `759ba5bc…eb1bb` == expected, exactly |
| Evaluate #0 round 1 | `AWAITING_DECISION`, pending `REPRODUCED`, scores 96/100/94 (min 94) |
| Challenge #0 | recorded, challenger `0xcbB0…87A4` |
| Evaluate #0 round 2 | `DECIDED`, `REPRODUCED`, scores 100/100/100 (min 100); bounty #0 `VERDICT_REPRODUCED`, reproducer credited 40 GEN |
| Withdraw #0 | reproducer withdrew 40 GEN; bounty #0 `BOUNTY_CLOSED`; reproducer reputation 10 |
| Bounty #1, 40 GEN | posted |
| Attempt #1, output `pi=9.99999` | output hash `1083c77d…6265e` != expected → `FAILED` |
| Evaluate #1 round 1 | `AWAITING_DECISION`, pending `FAILED`; LLM itself scored 0/0/0 (min 0) |
| Finalize #1 | `DECIDED`, `FAILED`; poster credited 40 GEN; reproducer reputation 5 (10 − 5) |
| Withdraw #1 | poster withdrew the 40 GEN refund; bounty #1 `BOUNTY_REFUNDED` |
| Bounty #2, 40 GEN | posted |
| Attempt #2, output `pi=3.14159`, log without `REPRO-END` | hashes match, log incomplete → `INCONCLUSIVE` |
| Evaluate #2 round 1 | `AWAITING_DECISION`, pending `INCONCLUSIVE`, scores 20/95/30 (min 20), after two dead-zone retries that wrote nothing |
| Finalize #2 | `DECIDED`, `INCONCLUSIVE`; reproducer credited 10 GEN, poster credited 30 GEN |
| Withdraw #2 × 2 | reproducer withdrew 10 GEN, poster withdrew 30 GEN; bounty #2 `BOUNTY_CLOSED` |
| Bounty #3, 40 GEN | posted, then cancelled by the poster |
| Withdraw #3 | poster withdrew the 40 GEN cancel refund; bounty #3 `BOUNTY_REFUNDED` |

Final GEN reconciliation (read back via RPC): total received 160 GEN == total paid out 160 GEN + 0 locked + 0 credits; contract balance 0 GEN. Poster 9950 GEN (10000 − 160 + 110), reproducer 10050 GEN (10000 + 40 + 10), challenger 10000 GEN (unchanged).

## Usage

Contract-only: no app frontend. Call it with `genlayer-js` 1.1.8 or any Studionet client. Scripts in this repo:

```bash
npm install
node scripts/deploy.mjs    # deploy to Studionet (ephemeral key if none supplied)
node scripts/flow.mjs      # full on-chain flow (20 txs), writes evidence.json
node scripts/verify.mjs    # independent re-check of every receipt + read-back
node scripts/simulate.mjs  # local mock of the decision rules (mock only, not consensus evidence)
python3 tests/test_local.py  # local mock tests, 102 checks (mock only)
```

### Call examples

All hashes below are SHA-256 hex of the demo inputs (recompute them; do not trust the strings):

```js
// Demo inputs (verified in tests/test_local.py against hashlib):
//   sha256("spec: compute pi to 5 decimals") = 9e0c088d4a4a58300e808f44646d87a9708057a98872de00eabb842be16f8e1f
//   sha256("reproduce.py v1")               = 3f9c3016763ca5b506de216152903050c37080f9bbce666d6c934207434dbeda
//   sha256("pi=3.14159")                    = 759ba5bc0ba9d4a301ef865bd4bbe968c8dec6a93b899912e8225bcd8f6eb1bb

// 1. Post a bounty of 40 GEN (40000000000000000000 wei), payable.
//    The GEN sent with the call is the bounty; it must be divisible by 4 wei.
await client.writeContract({
  address, functionName: "post_bounty",
  value: 40n * 10n ** 18n,
  args: ["9e0c088d4a4a58300e808f44646d87a9708057a98872de00eabb842be16f8e1f",
         "https://example.org/reproduce.py",
         "3f9c3016763ca5b506de216152903050c37080f9bbce666d6c934207434dbeda",
         "759ba5bc0ba9d4a301ef865bd4bbe968c8dec6a93b899912e8225bcd8f6eb1bb"],
});

// 2. Submit a replication: code hash, output text, run log with both markers.
await client.writeContract({
  address, functionName: "submit_reproduction", value: 0n,
  args: [0n, "3f9c3016763ca5b506de216152903050c37080f9bbce666d6c934207434dbeda",
         "pi=3.14159",
         "REPRO-START run reproduce.py --seed 7\nstep 1: load data ok\nstep 2: compute pi series ok\nRESULT pi=3.14159 matches expected\nREPRO-END exit 0"],
});

// 3. Evaluate (round 1), then finalize (permissionless) or challenge + re-evaluate.
await client.writeContract({ address, functionName: "evaluate_reproduction", args: [0n], value: 0n });
await client.writeContract({ address, functionName: "finalize_reproduction", args: [0n], value: 0n });

// 4. Withdraw the credited GEN (pull payment).
await client.writeContract({ address, functionName: "withdraw_payout", args: [], value: 0n });

// 5. Read back.
await client.readContract({ address, functionName: "get_attempt", args: [0n] });
await client.readContract({ address, functionName: "get_bounty", args: [0n] });
await client.readContract({ address, functionName: "get_credit", args: ["0x…"] });
await client.readContract({ address, functionName: "get_reputation", args: ["0x…"] });
await client.readContract({ address, functionName: "get_totals", args: [] });
```

Fund a test account with faucet GEN first (Studionet is gasless; the faucet
is free): `sim_fundAccount` with the checksummed address and the amount in
integer wei as a JS Number (10000 GEN = 10000 * 10 ** 18).

### Method reference

| method | type | notes |
|---|---|---|
| `post_bounty(spec_hash, code_ref, expected_code_hash, expected_output_hash)` | write, payable | GEN sent with the call is the bounty; must be divisible by 4 wei; returns bounty id |
| `submit_reproduction(bounty_id, code_hash, output_text, run_log)` | write | bounty must be `OPEN`; returns attempt id |
| `evaluate_reproduction(attempt_id)` | write | round 1 → `AWAITING_DECISION`; round 2 after challenge → `DECIDED` |
| `challenge_reproduction(attempt_id)` | write | only while `AWAITING_DECISION`, round 1, not by the reproducer; costs reputation, not GEN |
| `finalize_reproduction(attempt_id)` | write | permissionless; only when `AWAITING_DECISION`, round 1, unchallenged |
| `withdraw_payout()` | write | caller withdraws their own credit in GEN; zeroes the credit before transferring |
| `cancel_bounty(bounty_id)` | write | poster only, bounty `OPEN` or `REPRODUCTION_SUBMITTED`, no attempt `AWAITING_DECISION`; escrow credited back |
| `get_bounty(id)` / `get_attempt(id)` / `list_bounties(offset, limit)` / `list_attempts(offset, limit)` | view | JSON records |
| `get_bounty_count()` / `get_attempt_count()` | view | `u256` |
| `get_credit(address)` / `get_reputation(address)` | view | withdrawable credit in wei; reputation (starts at 0) |
| `get_totals()` | view | `total_received_wei`, `total_paid_out_wei`, `locked_wei`, `credits_total_wei`, `contract_balance_wei`, `accounted_wei` |

## Documentation

- [docs/mechanism.md](docs/mechanism.md) — state, money rules, deterministic rules, LLM scoring, worst-case spread calculation
- [docs/live-verification.md](docs/live-verification.md) — every core transaction receipt + read-back + GEN reconciliation
- [docs/REVIEWER.md](docs/REVIEWER.md) — reviewer fast path: where to start, shortest recheck steps
- [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) — limits, in neutral terms
- [deployment.json](deployment.json) — network, contract address, deploy tx, source SHA-256
- [evidence.json](evidence.json) — links + values only

## Tests

- `python3 tests/test_local.py` — 102 local mock checks: pure-Python SHA-256 vs `hashlib` test vectors, the deterministic verdict table, exhaustive score-band margin proof, the combine-verdict table, and a full state-machine simulation with canned LLM scores in wei (40 GEN bounties, REPRODUCED payout, FAILED refund, INCONCLUSIVE 10/30 GEN split, cancel, both challenge branches, dead-zone rejection, and the money invariant after every step). Local mocks only — they prove the rules are satisfiable and the margins hold; only the on-chain `evaluate_reproduction` transactions are consensus evidence.
- `node scripts/simulate.mjs` — exhaustive score-band enumeration in Node (mock only).

# Live verification

Network: Stable Studionet, Chain ID 61999, RPC https://studio.genlayer.com/api.
Contract: `0xFC225789B5322eE883b7FE96cf0353caB5C938c9`.
Deployed code SHA-256 `dfb7a6719c249c2aeaf58d7e9100ff64e4a005c6676032c19e760b718efae770`,
equal to `contracts/repro_bounty.py` at the deploy commit, verified by
reading the deployed code back via `gen_getContractCode` (base64),
decoding it, and hashing it. Re-check any time with
`node scripts/verify.mjs` (94 checks: code hash, every receipt,
every read-back against `evidence.json`, the GEN invariant, and the
final EOA balances).

All 21 transactions below were read back independently (fresh RPC
reads, not the flow script's own output): each receipt is FINALIZED
with `MAJORITY_AGREE`, and every state read-back matches
`evidence.json` exactly. All bounty money is real testnet GEN
(1 GEN = 10^18 wei), faucet-funded, zero cash cost.

## Transactions

| # | call | tx hash | receipt |
|---|---|---|---|
| 0 | deploy | `0xae0d289f30a41e808c819cb8fe5f31ffed40f8c27795dad51a3df94de8457f45` | FINALIZED, MAJORITY_AGREE |
| 1 | `post_bounty` #0, 40 GEN | `0x4aae86e937e2b15a4e957d012a790882e43c6dd8fcfb14aa87596687ada9a190` | FINALIZED, MAJORITY_AGREE |
| 2 | `submit_reproduction` #0 | `0xca04256522394ba17431367eb47dde7ec310a13f287eb4f09ad6003260db29f7` | FINALIZED, MAJORITY_AGREE |
| 3 | `evaluate_reproduction` #0 round 1 | `0x3035e0afb731ae43162774a4d8aac081c682b02e66923a2be579d355140a8a5a` | FINALIZED, MAJORITY_AGREE |
| 4 | `challenge_reproduction` #0 | `0xcb92190b0bb1960ae74cdd256b5d48d72c71c4fea9b868f29541ed6014a60459` | FINALIZED, MAJORITY_AGREE |
| 5 | `evaluate_reproduction` #0 round 2 | `0x72652bc5e1b1f6537837c72a2105d575badac8181b49fc59a27cf85523acbc45` | FINALIZED, MAJORITY_AGREE |
| 6 | `withdraw_payout` #0, 40 GEN | `0x6ca4328f078accc82766cf216661bd2de0dc8e10adae1fdb4d732fe127ac1558` | FINALIZED, MAJORITY_AGREE |
| 7 | `post_bounty` #1, 40 GEN | `0x1178e1980a36b1429aa56f8afc69acd88931d4e7e3b069752e2d62fb7f12add9` | FINALIZED, MAJORITY_AGREE |
| 8 | `submit_reproduction` #1 | `0x0dbaecf102a0352b510177683bb4f899124743de29feb8b59ac28f6c658d6347` | FINALIZED, MAJORITY_AGREE |
| 9 | `evaluate_reproduction` #1 round 1 | `0xaaf018ac95120410ac29d7d1bebc70a877644afd914e86dbd7c44333a3e0aecb` | FINALIZED, MAJORITY_AGREE |
| 10 | `finalize_reproduction` #1 | `0x53cfc6a3fdf706ebe1996e0b0e2f827e315d42b903beb8d1420a8ef3c46324f9` | FINALIZED, MAJORITY_AGREE |
| 11 | `withdraw_payout` #1, 40 GEN refund | `0x1924fa5b04d513bd056f0f57b80ef1a391029930fa90b5af5346dac859a0d0b6` | FINALIZED, MAJORITY_AGREE |
| 12 | `post_bounty` #2, 40 GEN | `0x2b6a73971f4ba86bc0d6df505f16c01105146282bbf2129d879098ea1ca34c2b` | FINALIZED, MAJORITY_AGREE |
| 13 | `submit_reproduction` #2 | `0x231f1b6361b5721c8f2d58c3599cd60b3f0e100f4e67fac5bd63a0660c9d16e1` | FINALIZED, MAJORITY_AGREE |
| 14 | `evaluate_reproduction` #2 round 1 | `0x32266a58c95f5c512f99011bea69e2d6f75f162c6278d42862b1187f10f224cc` | FINALIZED, MAJORITY_AGREE |
| 15 | `finalize_reproduction` #2 | `0x0366430d435e1af5f5b26e358ac0a106c70669ff32a8046bffd7a045ca79301f` | FINALIZED, MAJORITY_AGREE |
| 16 | `withdraw_payout` #2 reproducer, 10 GEN | `0xa71e56f6704478b8fe7666405fdc433281f45b572a18aa612c55615db240b3bf` | FINALIZED, MAJORITY_AGREE |
| 17 | `withdraw_payout` #2 poster, 30 GEN | `0x410c9e3b884cd52801c05495c7a0a0bae06407cf5432bb7bc510e6c220f5a289` | FINALIZED, MAJORITY_AGREE |
| 18 | `post_bounty` #3, 40 GEN | `0xc11e2806631d532d35fded9cb690249ca16af4384cff7c484a40872aedb8216d` | FINALIZED, MAJORITY_AGREE |
| 19 | `cancel_bounty` #3 | `0x1e15fe843ea55112f5249a589f03c9c8f9b71eed2113b668bddba592b125df75` | FINALIZED, MAJORITY_AGREE |
| 20 | `withdraw_payout` #3, 40 GEN refund | `0xce9b23f775b5a791db21617dd4d383bead75f64b72b9e1718089f46976b8a866` | FINALIZED, MAJORITY_AGREE |

## Read-backs (via RPC, after the flow)

Attempt #0 — `DECIDED`, verdict `REPRODUCED`, round 2, `first_verdict`
`REPRODUCED`, challenged by `0xcbB0…87A4`:

```json
{
  "id": 0,
  "bounty_id": 0,
  "reproducer": "0x07cC2EdfDdc5aAAac8f92769f8885c5E0eb971b8",
  "code_hash": "3f9c3016763ca5b506de216152903050c37080f9bbce666d6c934207434dbeda",
  "output_text": "pi=3.14159",
  "output_hash": "759ba5bc0ba9d4a301ef865bd4bbe968c8dec6a93b899912e8225bcd8f6eb1bb",
  "status": "DECIDED",
  "round": 2,
  "pending_verdict": null,
  "verdict": "REPRODUCED",
  "first_verdict": "REPRODUCED",
  "scores": {
    "log_consistency": 100,
    "output_plausibility": 100,
    "code_fidelity": 100,
    "min_score": 100
  },
  "challenged": true,
  "witness": null
}
```

Bounty #0 — `BOUNTY_CLOSED`, escrow 0, winner `0x07cC…71b8`.
The reproducer withdrew the full 40 GEN (40000000000000000000 wei).

Attempt #1 — `DECIDED`, verdict `FAILED`, round 1. The submitted
output `pi=9.99999` hashes to `1083c77d3cb94fe3…`, which differs
from the expected `759ba5bc0ba9d4a3…`, so the deterministic
check decided `FAILED`. The LLM agreed on the subjective side too,
scoring 0/0/0 (min 0):

```json
{
  "id": 1,
  "bounty_id": 1,
  "output_text": "pi=9.99999",
  "output_hash": "1083c77d3cb94fe3f789ee8146a0eb4fa9eb3450775ae05273e26e760dc6265e",
  "status": "DECIDED",
  "round": 1,
  "verdict": "FAILED",
  "scores": {
    "log_consistency": 0,
    "output_plausibility": 0,
    "code_fidelity": 0,
    "min_score": 0
  },
  "challenged": false,
  "witness": null
}
```

Bounty #1 — `BOUNTY_REFUNDED`, escrow 0. The poster withdrew the full
40 GEN refund. Reproducer reputation 10 − 5 = 5.

Attempt #2 — `DECIDED`, verdict `INCONCLUSIVE`, round 1. The hashes
match exactly, but the run log has no `REPRO-END` marker (it ends with
an interruption error), so the deterministic check decided
`INCONCLUSIVE`. Scores 20/95/30 (min 20):

```json
{
  "id": 2,
  "bounty_id": 2,
  "output_text": "pi=3.14159",
  "output_hash": "759ba5bc0ba9d4a301ef865bd4bbe968c8dec6a93b899912e8225bcd8f6eb1bb",
  "status": "DECIDED",
  "round": 1,
  "verdict": "INCONCLUSIVE",
  "scores": {
    "log_consistency": 20,
    "output_plausibility": 95,
    "code_fidelity": 30,
    "min_score": 20
  },
  "challenged": false,
  "witness": null
}
```

Bounty #2 — `BOUNTY_CLOSED`. The 25% / 75% split was exact in wei:
reproducer share 10000000000000000000 wei (10 GEN), poster share
30000000000000000000 wei (30 GEN); both sides withdrew.

Bounty #3 — `BOUNTY_REFUNDED` (cancelled by the poster before any
decision), escrow 0. The poster withdrew the full 40 GEN refund.

## GEN reconciliation (via RPC, after the flow)

```json
{
  "total_received_wei": 160000000000000000000,
  "total_paid_out_wei": 160000000000000000000,
  "locked_wei": 0,
  "credits_total_wei": 0,
  "contract_balance_wei": 0,
  "accounted_wei": 160000000000000000000
}
```

Poster `0xaD44…2ac9`: funded 10000 GEN, posted 160 GEN,
received back 110 GEN (40 FAILED refund + 30 INCONCLUSIVE share + 40
cancel refund) → 9950 GEN. Reproducer `0x07cC…71b8`: funded
10000 GEN, received 50 GEN (40 REPRODUCED + 10 INCONCLUSIVE share) →
10050 GEN. Challenger `0xcbB0…87A4`: funded 10000 GEN, no
money moved → 10000 GEN. Invariant holds: 160 GEN received == 160 GEN
paid out + 0 locked + 0 credits; contract balance 0 GEN.
Reputation: reproducer 5 (0 +10 −5 +0), challenger 0 (challenge failed:
both rounds agreed `REPRODUCED`, −5 floored at 0), poster 0.

## Dead-zone retries (FINALIZED, wrote nothing)

Two `evaluate_reproduction` #2 round 1 attempts finalized but wrote
nothing: the leader's scores landed in the 60–80 dead zone and the
validators rejected them, leaving the attempt `SUBMITTED`. The third
attempt passed (scores 20/95/30, min 20). Both rejected attempts are
recorded in `evidence.json` under `deadZoneRetries`:

- `0x6d52ee0f6a81bce9b0d66eba82344f5851559adea6d14b65506e9e32285fa581` (evaluate#2 round 1, try 1)
- `0xa16fee278d40514d88d19588b19c67e5a623297cb22dd02ec6db51390ae2a755` (evaluate#2 round 1, try 2)

## Earlier abandoned deployments (no state carried over)

The previous contract at `0x30e04052D3968E21f74FcB6cC4bBEFa9CC527472`
is abandoned: it kept bounty money in an internal ledger and no real GEN ever moved.

A first deployment of this version at
`0x6664D16C58A121823743A11BECe03A6f9769cb52` (deploy tx
`0xf50faa0934fd8963367256498c6ba425d42829139316c7c408ecf7f5aca4199f`)
was abandoned after its flow script stopped on a script-side
comparison bug right after posting bounty #0 (tx
`0x7d12f73831e3f8f51c76ffc26872a2fe2c025254d33fa7b58c8f58aff59da055`);
the ephemeral poster key was not retained, so the 40 faucet GEN
posted there is locked in that contract.

A second deployment at
`0x3e76dec0bd85e7c7a9a12a67BCF455434321fBaa` (deploy tx
`0xf96344f84547b3988d4b33993a3f68a3ad1160c6ab397d343143de34a393fe50`)
completed bounty #0 (`REPRODUCED`, 40 GEN paid out) but its flow
stopped at bounty #1: `evaluate_reproduction` #1 round 1 landed in
the dead zone three times in a row (txs
`0xeccddc39f2b718550fbfa6178c839e526872182d9f99d17bdfc7590e8e6d6be0`,
`0xbc6d4c9d31320279c380d8fd436f22e7f2a3ccf6f3ada40f77da11f527652c84`,
`0x574383c90c9893626a8764613997883733a8034802f46dce28b394616d369c82`),
each FINALIZED but writing nothing, and the flow process then exited;
the ephemeral flow keys were not retained, so the 40 faucet GEN
locked in its bounty #1 cannot be released. The FAILED case was
then made decisive (submitted output `pi=9.99999` against a log
claiming `pi=3.14159`) and the flow was re-run from a fresh
deployment, which is the contract verified above.

# Live verification

Network: Stable Studionet, Chain ID 61999, RPC https://studio.genlayer.com/api.
Contract: `0x30e04052D3968E21f74FcB6cC4bBEFa9CC527472`.
Deployed code SHA-256 `b61d458139954acb829ff88b1eaa9aa7431391ae1f5f2482805be674759960d8`,
equal to `contracts/repro_bounty.py` at the deploy commit, verified by
reading the deployed code back via `gen_getContractCode` and hashing it.
Re-check any time with `node scripts/verify.mjs` (41 checks: code hash,
every receipt, every read-back against `evidence.json`).

All 11 transactions below were read back independently (fresh RPC
reads, not the flow script's own output): each receipt is FINALIZED
with `MAJORITY_AGREE`, and every state read-back matches
`evidence.json` exactly.

## Transactions

| # | call | tx hash | receipt |
|---|---|---|---|
| 0 | deploy | `0x98fbfabf8a975ff2d7f20b48e14b02b633d3c8d39f21e300901d0ea3b2c990d3` | FINALIZED, MAJORITY_AGREE |
| 1 | `claim_demo_funds` (poster `0x355a…2400`) | `0x5f7b34ce27dc19a0dcc9f5099c05b37e9117467834dc407f87aae39d1dba14f2` | FINALIZED, MAJORITY_AGREE |
| 2 | `post_bounty` #0, 4000 | `0x99c8bf027889cca32fc6303d765e150f4ef10030dd28048962d35e73cee2ce61` | FINALIZED, MAJORITY_AGREE |
| 3 | `submit_replication` #0 | `0x60c063eb6eed15d56261815dde1ef5bcf9193c4e2e0bc504ba16fe96d65492de` | FINALIZED, MAJORITY_AGREE |
| 4 | `evaluate_replication` #0 round 1 | `0xec02ac214527fed207147778496c3ea68b77197a7d432261ec51901154326e7d` | FINALIZED, MAJORITY_AGREE |
| 5 | `challenge_replication` #0 | `0x036f58bb869777bf400fafcbbd874782312502ca3eb8ff9cbc64a8c540a0eebe` | FINALIZED, MAJORITY_AGREE |
| 6 | `evaluate_replication` #0 round 2 | `0xdc4964647014a4e7afd1b50fb79443f00d028c720c1c818d71a0866a9b62629e` | FINALIZED, MAJORITY_AGREE |
| 7 | `post_bounty` #1, 2000 | `0x2f792848fe622a43475f617510c98d5d2ee858c306c8f1772030004e29c3f6d9` | FINALIZED, MAJORITY_AGREE |
| 8 | `submit_replication` #1 | `0xe91e5e9898ce60e0586c47bc3723103b4bfdd53b4616b4cea63af888d8cbbae6` | FINALIZED, MAJORITY_AGREE |
| 9 | `evaluate_replication` #1 round 1 | `0xf389253e5905bd7a17dd0f789c2c9133c75a227d7ca0889190614e5a48efb977` | FINALIZED, MAJORITY_AGREE |
| 10 | `finalize_replication` #1 | `0x572551569661ee3791cf3ffcd16ba8dd7a2266be156649ceb3e8d830301461c7` | FINALIZED, MAJORITY_AGREE |

## Read-backs (via RPC, after the flow)

Attempt #0 — `FINALIZED`, verdict `REPRODUCED`, round 2, `first_verdict`
`REPRODUCED`, challenged by `0xD9eD…6126`:

```json
{
  "id": 0, "bounty_id": 0,
  "reproducer": "0xCAe58dc17c308cFb39f957Dc9294911353461E75",
  "code_hash": "3f9c3016763ca5b506de216152903050c37080f9bbce666d6c934207434dbeda",
  "output_text": "pi=3.14159",
  "output_hash": "759ba5bc0ba9d4a301ef865bd4bbe968c8dec6a93b899912e8225bcd8f6eb1bb",
  "status": "FINALIZED", "round": 2, "pending_verdict": null,
  "verdict": "REPRODUCED", "first_verdict": "REPRODUCED",
  "scores": {"log_consistency": 95, "output_plausibility": 90, "code_fidelity": 85, "min_score": 85},
  "challenged": true, "witness": null
}
```

Bounty #0 — `CLOSED`, escrow 0, winner `0xCAe58dc17c308cFb39f957Dc9294911353461E75`.

Attempt #1 — `FINALIZED`, verdict `FAILED`, round 1. The submitted
output `pi=3.14000` hashes to `e49f777154e45ce08f54d60da9241a6bde2dcb8bfdb2482c2f2fbf4a8dfb88b1`,
which differs from the expected `759ba5bc…eb1bb`, so the deterministic
check decided `FAILED`. The LLM agreed on the subjective side too,
scoring `output_plausibility` 12 (the log claims `pi=3.14159` while the
submitted output says `pi=3.14000`):

```json
{
  "id": 1, "bounty_id": 1,
  "output_text": "pi=3.14000",
  "output_hash": "e49f777154e45ce08f54d60da9241a6bde2dcb8bfdb2482c2f2fbf4a8dfb88b1",
  "status": "FINALIZED", "round": 1, "pending_verdict": null,
  "verdict": "FAILED", "first_verdict": null,
  "scores": {"log_consistency": 92, "output_plausibility": 12, "code_fidelity": 88, "min_score": 12},
  "challenged": false, "witness": null
}
```

Bounty #1 — `OPEN`, escrow 2000 (a `FAILED` finalization leaves the
escrow locked for a later attempt).

Final ledger state: reproducer balance 4000, poster balance 4000,
reproducer reputation 105 (100 +10 for `REPRODUCED`, −5 for `FAILED`),
challenger reputation 95 (the challenge failed because both rounds
agreed on `REPRODUCED`).

## Earlier invalid deployment (abandoned, no state written)

The first deployment attempt produced contract
`0xc8572CD4C9578FC1000eBd89dfd4E40746005bEb` (deploy tx
`0x806e0ad392dbf4374d0184e36d05f66b3ec43b75c062a9bd98bc770da052857b`).
Its receipt reported FINALIZED / MAJORITY_AGREE, but the contract was
invalid: GenVM rejected the file's header layout (a comment line placed
directly after the `Depends` line), so `gen_call` / `gen_getContractCode`
returned "Contract not found" and the next write reached NO_MAJORITY
with 0 rounds. That contract was abandoned — no state was ever written
through it — and the header was restructured (Depends line first,
explanation as a docstring). The deployed contract above is the second
attempt. The header rule was confirmed by schema checks against
`gen_getContractSchemaForCode` on both layouts.

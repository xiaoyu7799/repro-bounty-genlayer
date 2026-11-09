# Reviewer fast path

Start here: [README.md](../README.md) (one page: what it is, the
decision rule, the verified flow, call examples), then
[mechanism.md](mechanism.md) (state, money rules, worst-case spread
calculation).

## Shortest recheck (about 5 minutes, no keys needed)

1. Confirm the deployed code is the repo code:
   - Contract: `0xFC225789B5322eE883b7FE96cf0353caB5C938c9`
   - `gen_getContractCode` on that address, base64-decode it, SHA-256 it,
     compare with
     `dfb7a6719c249c2aeaf58d7e9100ff64e4a005c6676032c19e760b718efae770`
     (the SHA-256 of `contracts/repro_bounty.py` at HEAD).
2. Re-run the independent check (needs only `npm install`, no keys):
   `node scripts/verify.mjs` — 94 checks: code hash, all 21 receipts
   FINALIZED + MAJORITY_AGREE, and every read-back against
   `evidence.json`, plus the GEN invariant and final EOA balances.
3. Spot-check one read-back by hand:
   `get_attempt(0)` → `DECIDED`, `REPRODUCED`, round 2, scores
   100/100/100; `get_bounty(0)` → `BOUNTY_CLOSED`, escrow 0.
4. Spot-check the adversarial case: `get_attempt(1)` → `DECIDED`,
   `FAILED`; its `output_hash` (`1083c77d…`) differs from the expected
   `759ba5bc…`, and `get_bounty(1)` is `BOUNTY_REFUNDED` with escrow 0.
5. Spot-check the money: `get_totals()` → received 160 GEN, paid out
   160 GEN, locked 0, credits 0, contract balance 0.

## Where the mechanism lives

- Verdict rules: `contracts/repro_bounty.py`, `_deterministic_verdict`
  (exact hash/code/log checks), the `judge` / `validate` pair inside
  `evaluate_reproduction` (LLM scores, tolerance 10, dead zone 60–80),
  `_combine_verdict` (deterministic verdict always wins).
- Money rules: `post_bounty` (payable, GEN locked), `_apply_final_verdict`
  (credits the escrow: full / full refund / 25%–75% split),
  `withdraw_payout` (zeroes the credit before transferring),
  `get_totals` (the invariant).
- Worst-case spread proof: [mechanism.md](mechanism.md), section
  "Worst-case spread calculation" — 0 verdict flips, 0 GEN difference,
  with the edge cases (missing log, truncated output, close-but-different
  hash, split rounding) covered by the same rules.
- Local mock tests (mock only, not consensus evidence):
  `python3 tests/test_local.py` (102 checks) and
  `node scripts/simulate.mjs` (exhaustive score-band enumeration).

# Reviewer fast path

Start here: [README.md](../README.md) (one page: what it is, the
decision rule, the verified flow, call examples), then
[mechanism.md](mechanism.md) (state, rules, worst-case spread
calculation).

## Shortest recheck (about 5 minutes, no keys needed)

1. Confirm the deployed code is the repo code:
   - Contract: `0x30e04052D3968E21f74FcB6cC4bBEFa9CC527472`
   - `gen_getContractCode` on that address, SHA-256 it, compare with
     `b61d458139954acb829ff88b1eaa9aa7431391ae1f5f2482805be674759960d8`
     (the SHA-256 of `contracts/repro_bounty.py` at HEAD).
2. Re-run the independent check (needs only `npm install`, no keys):
   `node scripts/verify.mjs` — 41 checks: code hash, all 11 receipts
   FINALIZED + MAJORITY_AGREE, and every read-back against
   `evidence.json`.
3. Spot-check one read-back by hand:
   `get_attempt(0)` → `FINALIZED`, `REPRODUCED`, round 2, scores
   95/90/85; `get_bounty(0)` → `CLOSED`, escrow 0.
4. Spot-check the adversarial case: `get_attempt(1)` → `FINALIZED`,
   `FAILED`; its `output_hash` (`e49f7771…`) differs from the expected
   `759ba5bc…`, and `get_bounty(1)` is still `OPEN` with escrow 2000.

## Where the mechanism lives

- Verdict rules: `contracts/repro_bounty.py`, `_deterministic_verdict`
  (exact hash/code/log checks), the `judge` / `validate` pair inside
  `evaluate_replication` (LLM scores, tolerance 10, dead zone 60–80),
  `_combine_verdict` (deterministic verdict always wins).
- Worst-case spread proof: [mechanism.md](mechanism.md), section
  "Worst-case spread calculation" — 0 verdict flips, 0 mGEN difference,
  with the edge cases (missing log, truncated output, close-but-different
  hash) covered by the same rules.
- Local mock tests (mock only, not consensus evidence):
  `python3 tests/test_local.py` (62 checks) and
  `node scripts/simulate.mjs` (exhaustive score-band enumeration).

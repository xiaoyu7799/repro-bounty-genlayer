# Known limitations

- All bounty money is real testnet GEN on Stable Studionet
  (Chain ID 61999), funded from the Studionet faucet at zero cash
  cost. The GEN has no cash value and the contract is not connected
  to any mainnet.
- The contract checks the evidence it is given: exact hash equality,
  exact code-hash equality, and run-log markers, plus an LLM judgement
  of the log's credibility. It cannot observe the reproducer's machine,
  so a fabricated log that reads credibly and an output text whose hash
  matches the expected hash are judged on the log alone.
- A `FAILED` finalization refunds the full escrow to the poster and
  the bounty ends; there is no retry of the same bounty. A poster who
  wants another attempt posts a new bounty.
- The poster can cancel a bounty only while no attempt is awaiting a
  decision; there is no deadline or expiry that releases escrow
  automatically.
- Reputation is a number attached to an address, starting at 0. It
  does not identify a real researcher, and a new address starts fresh.
  A failed challenge costs 5 reputation, floored at 0, so a challenger
  starting at 0 shows no visible change.
- Run logs are capped at 4000 characters and output text at 2000
  characters; longer evidence must be summarized or referenced by hash
  before submission.
- LLM scores in the 60–80 dead zone are rejected by validators and the
  evaluation must be retried; the attempt stays `SUBMITTED` in that
  case and no verdict is written.
- A bounty must be divisible by 4 wei at posting time so the
  INCONCLUSIVE 25% / 75% split is exact in wei.
- The first deployment of this version produced a contract that was
  abandoned before any state was written: its deploy transaction
  finalized, but the flow script stopped on a script-side comparison
  bug after posting the first bounty, and the ephemeral poster key
  was not retained, so the 40 faucet GEN posted there is locked in
  that contract. That contract is not the deployed contract; see
  `docs/live-verification.md` for the abandoned address.

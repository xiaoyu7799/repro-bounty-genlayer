# Known limitations

- All bounty money is simulated mGEN ledger units inside this contract.
  No real GEN moves, and no real GEN can be deposited or withdrawn.
- The contract checks the evidence it is given: exact hash equality,
  exact code-hash equality, and run-log markers, plus an LLM judgement
  of the log's credibility. It cannot observe the reproducer's machine,
  so a fabricated log that reads credibly and an output text whose hash
  matches the expected hash are judged on the log alone.
- A `FAILED` or `INCONCLUSIVE` finalization leaves the escrow locked in
  the bounty for a later attempt. The poster can cancel an `OPEN`
  bounty only while no attempt is under evaluation; there is no
  deadline or expiry that releases escrow automatically.
- Reputation is a number attached to an address, starting at 100. It
  does not identify a real researcher, and a new address starts fresh.
- Run logs are capped at 4000 characters and output text at 2000
  characters; longer evidence must be summarized or referenced by hash
  before submission.
- LLM scores in the 60–80 dead zone are rejected by validators and the
  evaluation must be retried; the attempt stays `SUBMITTED` in that
  case and no verdict is written.
- The first deployment attempt of this contract produced an invalid
  contract (GenVM rejected the file's header layout: a comment line
  placed directly after the `Depends` line) and was abandoned before
  any state was written. The deployed contract at
  `0x30e04052D3968E21f74FcB6cC4bBEFa9CC527472` is the second attempt,
  with the header restructured; its deployed code SHA-256 matches the
  repository file exactly.

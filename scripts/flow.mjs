/* End-to-end on-chain flow against an already-deployed ReproBounty contract.
 *
 * Usage:
 *   CONTRACT_ADDRESS=0x... node scripts/flow.mjs
 *   # Keys are ephemeral per run (Studionet is gasless, faucet GEN is
 *   # free); no key is written to disk. Three roles use three ephemeral
 *   accounts: poster, reproducer, challenger. Each is funded with
 *   10000 GEN via sim_fundAccount (integer wei as a JS Number).
 *
 * Money is real testnet GEN (1 GEN = 10^18 wei). Every bounty is 40 GEN,
 * so the INCONCLUSIVE 25% / 75% split is exact (10 GEN / 30 GEN).
 *
 * Steps (20 transactions, one per branch):
 *   poster:     post_bounty #0, 40 GEN (payable)
 *   reproducer: submit_reproduction #0 (genuine output + complete log)
 *   poster:     evaluate_reproduction #0, round 1 -> AWAITING_DECISION, pending REPRODUCED
 *   challenger: challenge_reproduction #0
 *   reproducer: evaluate_reproduction #0, round 2 -> DECIDED REPRODUCED,
 *               40 GEN credited to the reproducer
 *   reproducer: withdraw_payout -> 40 GEN to the reproducer, bounty #0 BOUNTY_CLOSED
 *   poster:     post_bounty #1, 40 GEN
 *   reproducer: submit_reproduction #1 (wrong output text)
 *   poster:     evaluate_reproduction #1, round 1 -> pending FAILED
 *               (deterministic hash mismatch; LLM scores cannot rescue it)
 *   poster:     finalize_reproduction #1 -> DECIDED FAILED, 40 GEN credited to the poster
 *   poster:     withdraw_payout -> 40 GEN refund, bounty #1 BOUNTY_REFUNDED
 *   poster:     post_bounty #2, 40 GEN
 *   reproducer: submit_reproduction #2 (matching hashes, log missing REPRO-END)
 *   poster:     evaluate_reproduction #2, round 1 -> pending INCONCLUSIVE
 *   poster:     finalize_reproduction #2 -> DECIDED INCONCLUSIVE,
 *               10 GEN credited to the reproducer, 30 GEN to the poster
 *   reproducer: withdraw_payout -> 10 GEN
 *   poster:     withdraw_payout -> 30 GEN, bounty #2 BOUNTY_CLOSED
 *   poster:     post_bounty #3, 40 GEN
 *   poster:     cancel_bounty #3 -> 40 GEN credited to the poster, BOUNTY_REFUNDED
 *   poster:     withdraw_payout -> 40 GEN
 *
 * Every step is read back via RPC. Writes evidence.json: the `txs`
 * object lists ONLY transaction hashes (0x...), nothing else.
 * If an evaluation lands in the dead-score zone (60-80), validators
 * reject it, the attempt stays SUBMITTED, and the script retries that
 * evaluation (up to 3 tries).
 */
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createClient, createAccount, generatePrivateKey } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { TransactionStatus } from "genlayer-js/types";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const deployment = JSON.parse(readFileSync(path.join(root, "deployment.json"), "utf-8"));
const address = process.env.CONTRACT_ADDRESS || deployment.contractAddress;
if (!address) throw new Error("No contract address: set CONTRACT_ADDRESS or run deploy first");

const sha256 = (s) => createHash("sha256").update(s, "utf-8").digest("hex");
const GEN = 10n ** 18n;
const BOUNTY_GEN = 40n;
const FUND_GEN = 10000;

const poster = createAccount(generatePrivateKey());
const reproducer = createAccount(generatePrivateKey());
const challenger = createAccount(generatePrivateKey());
const posterClient = createClient({ chain: studionet, account: poster });
const reproClient = createClient({ chain: studionet, account: reproducer });
const challClient = createClient({ chain: studionet, account: challenger });
console.log("Contract:", address);
console.log("Poster:", poster.address);
console.log("Reproducer:", reproducer.address);
console.log("Challenger:", challenger.address);

const STATUS = { 0: "UNINITIALIZED", 1: "PENDING", 2: "PROPOSING", 3: "COMMITTING", 4: "REVEALING", 5: "ACCEPTED", 6: "UNDETERMINED", 7: "FINALIZED", 8: "CANCELED" };

async function fund(client, account, label) {
  const tx = await client.request({
    method: "sim_fundAccount",
    params: [account.address, FUND_GEN * 10 ** 18],
  });
  const bal = (await client.getBalance({ address: account.address })).toString();
  console.log(`${label} funded: ${bal} wei (fund tx ${String(tx).slice(0, 18)}…)`);
  if (bal !== (BigInt(FUND_GEN) * GEN).toString()) throw new Error(`${label} fund amount mismatch: ${bal}`);
  return String(tx);
}

async function waitFinal(client, hash, label) {
  console.log(`${label} tx:`, hash);
  const receipt = await client.waitForTransactionReceipt({
    hash,
    status: TransactionStatus.FINALIZED,
    retries: 180,
    interval: 5000,
  });
  const status = receipt.statusName ?? STATUS[receipt.status] ?? String(receipt.status ?? "");
  console.log(`${label} final:`, status);
  if (status !== "FINALIZED") throw new Error(`${label} did not finalize: ${status}`);
  return receipt;
}

async function write(client, functionName, args, label, value = 0n) {
  const hash = await client.writeContract({ address, functionName, args, value, leaderOnly: false });
  await waitFinal(client, hash, label);
  return hash;
}

async function read(client, functionName, args) {
  const raw = await client.readContract({ address, functionName, args });
  if (typeof raw === "string" && (raw.startsWith("{") || raw.startsWith("["))) return JSON.parse(raw);
  return raw;
}

const eoaBalance = async (client, account) =>
  (await client.getBalance({ address: account.address })).toString();

const GOOD_OUTPUT = "pi=3.14159";
const GOOD_LOG =
  "REPRO-START run reproduce.py --seed 7\n" +
  "step 1: load data ok\nstep 2: compute pi series ok\n" +
  "RESULT pi=3.14159 matches expected\nREPRO-END exit 0";
const SHORT_LOG =
  "REPRO-START run reproduce.py --seed 7\n" +
  "step 1: load data ok\nstep 2: compute pi series ok\n" +
  "RESULT pi=3.14159 matches expected\n" +
  "ERROR: process terminated unexpectedly, no REPRO-END, run did not complete\n";
const CODE_HASH = sha256("reproduce.py v1");
const SPEC_HASH = sha256("spec: compute pi to 5 decimals");
const EXPECTED_OUT_HASH = sha256(GOOD_OUTPUT);
console.log("Expected output hash:", EXPECTED_OUT_HASH);

const txs = {};
const funding = {};

// 0. Fund all three roles with 10000 GEN each.
funding.posterFundTx = await fund(posterClient, poster, "Poster");
funding.reproducerFundTx = await fund(reproClient, reproducer, "Reproducer");
funding.challengerFundTx = await fund(challClient, challenger, "Challenger");
const eoaBefore = {
  poster: await eoaBalance(posterClient, poster),
  reproducer: await eoaBalance(reproClient, reproducer),
  challenger: await eoaBalance(challClient, challenger),
};

// 1. Poster posts bounty #0, 40 GEN payable.
txs.postBounty0Tx = await write(
  posterClient, "post_bounty",
  [SPEC_HASH, "https://example.org/reproduce.py", CODE_HASH, EXPECTED_OUT_HASH],
  "post_bounty#0", BOUNTY_GEN * GEN
);
let bounty0 = await read(posterClient, "get_bounty", [0n]);
console.log("Bounty #0:", JSON.stringify(bounty0));
if (bounty0.status !== "OPEN" || String(bounty0.amount_wei) !== (BOUNTY_GEN * GEN).toString())
  throw new Error("Bounty #0 post read-back mismatch");

// 2. Reproducer submits a genuine replication.
txs.submit0Tx = await write(
  reproClient, "submit_reproduction", [0n, CODE_HASH, GOOD_OUTPUT, GOOD_LOG],
  "submit_reproduction#0"
);
const attempt0 = await read(posterClient, "get_attempt", [0n]);
console.log("Attempt #0 output_hash:", attempt0.output_hash);
if (attempt0.output_hash !== EXPECTED_OUT_HASH) throw new Error("output_hash mismatch on read-back");
bounty0 = await read(posterClient, "get_bounty", [0n]);
if (bounty0.status !== "REPRODUCTION_SUBMITTED") throw new Error("Bounty #0 should be REPRODUCTION_SUBMITTED");

// 3. Evaluate round 1 (retry if the scores land in the dead zone).
const deadZoneRetries = [];
async function evaluateWithRetry(client, attemptId, label) {
  for (let attempt = 1; attempt <= 12; attempt++) {
    const hash = await write(client, "evaluate_reproduction", [attemptId], `${label} (try ${attempt})`);
    const state = await read(posterClient, "get_attempt", [attemptId]);
    console.log(`${label} state after try ${attempt}:`, state.status, "round", state.round, "pending", state.pending_verdict, "verdict", state.verdict, "scores", JSON.stringify(state.scores));
    if (state.status === "AWAITING_DECISION" || state.status === "DECIDED") return { hash, state };
    console.log(`${label}: still SUBMITTED (dead-zone scores rejected), retrying...`);
    deadZoneRetries.push({ label, try: attempt, txHash: hash, note: "FINALIZED but wrote nothing: leader scores in the 60-80 dead zone were rejected by validators" });
  }
  throw new Error(`${label} did not move out of SUBMITTED after 12 tries`);
}
const ev0 = await evaluateWithRetry(posterClient, 0n, "evaluate#0 round 1");
txs.evaluate0Round1Tx = ev0.hash;
if (ev0.state.pending_verdict !== "REPRODUCED") throw new Error(`Round 1 pending verdict is ${ev0.state.pending_verdict}, expected REPRODUCED`);

// 4. Challenger challenges; 5. round 2 finalizes directly.
txs.challenge0Tx = await write(challClient, "challenge_reproduction", [0n], "challenge#0");
const ev0b = await evaluateWithRetry(reproClient, 0n, "evaluate#0 round 2");
txs.evaluate0Round2Tx = ev0b.hash;
if (ev0b.state.status !== "DECIDED" || ev0b.state.verdict !== "REPRODUCED") {
  throw new Error(`Round 2 did not finalize REPRODUCED: ${JSON.stringify(ev0b.state)}`);
}
bounty0 = await read(posterClient, "get_bounty", [0n]);
const reproCredit0 = String(await read(posterClient, "get_credit", [reproducer.address]));
const reproRep0 = String(await read(posterClient, "get_reputation", [reproducer.address]));
console.log("Bounty #0 after round 2:", JSON.stringify(bounty0));
console.log("Reproducer credit:", reproCredit0, "wei; reputation:", reproRep0);
if (String(reproCredit0) !== (BOUNTY_GEN * GEN).toString()) throw new Error("Reproducer credit should be 40 GEN");

// 6. Reproducer withdraws 40 GEN (pull payment).
txs.withdraw0Tx = await write(reproClient, "withdraw_payout", [], "withdraw_payout#0");
await new Promise((r) => setTimeout(r, 8000));
const reproEoaAfter0 = await eoaBalance(reproClient, reproducer);
bounty0 = await read(posterClient, "get_bounty", [0n]);
console.log("Reproducer EOA after withdraw #0:", reproEoaAfter0, "wei; bounty #0:", bounty0.status);
if (bounty0.status !== "BOUNTY_CLOSED") throw new Error("Bounty #0 should be BOUNTY_CLOSED after full payout");
if (reproEoaAfter0 !== (BigInt(FUND_GEN + 40) * GEN).toString()) throw new Error(`Reproducer EOA should be 10040 GEN, got ${reproEoaAfter0}`);

// 7. Poster posts bounty #1 (40 GEN). 8. Reproducer submits a WRONG output.
txs.postBounty1Tx = await write(
  posterClient, "post_bounty",
  [SPEC_HASH, "https://example.org/reproduce.py", CODE_HASH, EXPECTED_OUT_HASH],
  "post_bounty#1", BOUNTY_GEN * GEN
);
const WRONG_OUTPUT = "pi=9.99999";  // blatantly contradicts the log RESULT pi=3.14159, so the LLM scores it decisively low
txs.submit1Tx = await write(
  reproClient, "submit_reproduction", [1n, CODE_HASH, WRONG_OUTPUT, GOOD_LOG],
  "submit_reproduction#1"
);
const attempt1 = await read(posterClient, "get_attempt", [1n]);
console.log("Attempt #1 output_hash:", attempt1.output_hash, "(expected:", EXPECTED_OUT_HASH + ")");
if (attempt1.output_hash === EXPECTED_OUT_HASH) throw new Error("wrong output hashed equal?!");

// 9. Evaluate #1 round 1 -> pending FAILED (deterministic hash mismatch).
const ev1 = await evaluateWithRetry(posterClient, 1n, "evaluate#1 round 1");
txs.evaluate1Round1Tx = ev1.hash;
if (ev1.state.pending_verdict !== "FAILED") throw new Error(`Round 1 pending verdict is ${ev1.state.pending_verdict}, expected FAILED`);
const attempt1After = await read(posterClient, "get_attempt", [1n]);
console.log("Attempt #1 witness:", JSON.stringify(attempt1After.witness));

// 10. Finalize #1 (no challenge) -> DECIDED FAILED, 40 GEN credited to the poster.
txs.finalize1Tx = await write(posterClient, "finalize_reproduction", [1n], "finalize#1");
const attempt1Final = await read(posterClient, "get_attempt", [1n]);
let bounty1 = await read(posterClient, "get_bounty", [1n]);
const posterCredit1 = String(await read(posterClient, "get_credit", [poster.address]));
const reproRepFinal = String(await read(posterClient, "get_reputation", [reproducer.address]));
console.log("Attempt #1 final:", JSON.stringify(attempt1Final));
console.log("Bounty #1 final:", JSON.stringify(bounty1));
console.log("Poster credit:", posterCredit1, "wei; reproducer reputation:", reproRepFinal);
if (attempt1Final.status !== "DECIDED" || attempt1Final.verdict !== "FAILED") {
  throw new Error("Attempt #1 did not finalize FAILED");
}
if (bounty1.status !== "VERDICT_FAILED" || String(bounty1.poster_share_wei) !== (BOUNTY_GEN * GEN).toString()) {
  throw new Error("Bounty #1 should be VERDICT_FAILED with a 40 GEN poster share");
}

// 11. Poster withdraws the 40 GEN refund.
txs.withdraw1Tx = await write(posterClient, "withdraw_payout", [], "withdraw_payout#1");
await new Promise((r) => setTimeout(r, 8000));
bounty1 = await read(posterClient, "get_bounty", [1n]);
console.log("Bounty #1 after refund withdraw:", bounty1.status);
if (bounty1.status !== "BOUNTY_REFUNDED") throw new Error("Bounty #1 should be BOUNTY_REFUNDED after refund paid");

// 12. Poster posts bounty #2 (40 GEN). 13. Reproducer submits with an
// incomplete log (matching hashes, no REPRO-END marker).
txs.postBounty2Tx = await write(
  posterClient, "post_bounty",
  [SPEC_HASH, "https://example.org/reproduce.py", CODE_HASH, EXPECTED_OUT_HASH],
  "post_bounty#2", BOUNTY_GEN * GEN
);
txs.submit2Tx = await write(
  reproClient, "submit_reproduction", [2n, CODE_HASH, GOOD_OUTPUT, SHORT_LOG],
  "submit_reproduction#2"
);

// 14. Evaluate #2 round 1 -> pending INCONCLUSIVE.
const ev2 = await evaluateWithRetry(posterClient, 2n, "evaluate#2 round 1");
txs.evaluate2Round1Tx = ev2.hash;
if (ev2.state.pending_verdict !== "INCONCLUSIVE") throw new Error(`Round 1 pending verdict is ${ev2.state.pending_verdict}, expected INCONCLUSIVE`);

// 15. Finalize #2 -> DECIDED INCONCLUSIVE, 10 GEN to reproducer, 30 GEN to poster.
txs.finalize2Tx = await write(posterClient, "finalize_reproduction", [2n], "finalize#2");
const attempt2Final = await read(posterClient, "get_attempt", [2n]);
let bounty2 = await read(posterClient, "get_bounty", [2n]);
console.log("Attempt #2 final:", JSON.stringify(attempt2Final));
console.log("Bounty #2 final:", JSON.stringify(bounty2));
if (attempt2Final.status !== "DECIDED" || attempt2Final.verdict !== "INCONCLUSIVE") {
  throw new Error("Attempt #2 did not finalize INCONCLUSIVE");
}
if (String(bounty2.reproducer_share_wei) !== (10n * GEN).toString() || String(bounty2.poster_share_wei) !== (30n * GEN).toString()) {
  throw new Error("INCONCLUSIVE split should be 10 GEN / 30 GEN");
}

// 16. Reproducer withdraws 10 GEN; 17. poster withdraws 30 GEN.
txs.withdraw2ReproTx = await write(reproClient, "withdraw_payout", [], "withdraw_payout#2-reproducer");
await new Promise((r) => setTimeout(r, 8000));
bounty2 = await read(posterClient, "get_bounty", [2n]);
console.log("Bounty #2 after reproducer withdraw:", bounty2.status);
if (bounty2.status !== "VERDICT_INCONCLUSIVE") throw new Error("Bounty #2 should stay VERDICT_INCONCLUSIVE until both shares are paid");
txs.withdraw2PosterTx = await write(posterClient, "withdraw_payout", [], "withdraw_payout#2-poster");
await new Promise((r) => setTimeout(r, 8000));
bounty2 = await read(posterClient, "get_bounty", [2n]);
console.log("Bounty #2 after poster withdraw:", bounty2.status);
if (bounty2.status !== "BOUNTY_CLOSED") throw new Error("Bounty #2 should be BOUNTY_CLOSED after both shares are paid");

// 18. Poster posts bounty #3 (40 GEN). 19. Poster cancels it.
txs.postBounty3Tx = await write(
  posterClient, "post_bounty",
  [SPEC_HASH, "https://example.org/reproduce.py", CODE_HASH, EXPECTED_OUT_HASH],
  "post_bounty#3", BOUNTY_GEN * GEN
);
txs.cancel3Tx = await write(posterClient, "cancel_bounty", [3n], "cancel_bounty#3");
let bounty3 = await read(posterClient, "get_bounty", [3n]);
console.log("Bounty #3 after cancel:", JSON.stringify(bounty3));
if (bounty3.status !== "BOUNTY_REFUNDED") throw new Error("Bounty #3 should be BOUNTY_REFUNDED after cancel");

// 20. Poster withdraws the 40 GEN cancel refund.
txs.withdraw3Tx = await write(posterClient, "withdraw_payout", [], "withdraw_payout#3");
await new Promise((r) => setTimeout(r, 8000));
bounty3 = await read(posterClient, "get_bounty", [3n]);
console.log("Bounty #3 final:", bounty3.status);

// Final state: totals + EOA balances + reputation.
const totals = await read(posterClient, "get_totals", []);
const eoaAfter = {
  poster: await eoaBalance(posterClient, poster),
  reproducer: await eoaBalance(reproClient, reproducer),
  challenger: await eoaBalance(challClient, challenger),
};
const finalReputation = {
  poster: String(await read(posterClient, "get_reputation", [poster.address])),
  reproducer: String(await read(posterClient, "get_reputation", [reproducer.address])),
  challenger: String(await read(posterClient, "get_reputation", [challenger.address])),
};
const finalCredits = {
  poster: String(await read(posterClient, "get_credit", [poster.address])),
  reproducer: String(await read(posterClient, "get_credit", [reproducer.address])),
  challenger: String(await read(posterClient, "get_credit", [challenger.address])),
};
console.log("Totals:", JSON.stringify(totals));
console.log("EOA after:", JSON.stringify(eoaAfter));
console.log("Reputation:", JSON.stringify(finalReputation));
console.log("Credits:", JSON.stringify(finalCredits));
if (String(totals.total_received_wei) !== (160n * GEN).toString()) throw new Error("total_received should be 160 GEN");
if (String(totals.total_paid_out_wei) !== (160n * GEN).toString()) throw new Error("total_paid_out should be 160 GEN");
if (String(totals.locked_wei) !== "0" || String(totals.credits_total_wei) !== "0" || String(totals.contract_balance_wei) !== "0") {
  throw new Error("contract should hold 0 GEN at the end");
}
if (eoaAfter.poster !== (BigInt(10000 - 160 + 110) * GEN).toString()) throw new Error(`Poster EOA mismatch: ${eoaAfter.poster}`);
if (eoaAfter.reproducer !== (BigInt(10000 + 50) * GEN).toString()) throw new Error(`Reproducer EOA mismatch: ${eoaAfter.reproducer}`);
if (eoaAfter.challenger !== (BigInt(FUND_GEN) * GEN).toString()) throw new Error(`Challenger EOA mismatch: ${eoaAfter.challenger}`);

// Evidence: txs lists ONLY transaction hashes.
const attempt0Final = await read(posterClient, "get_attempt", [0n]);
const evidence = {
  network: "Stable Studionet",
  chainId: 61999,
  rpcUrl: "https://studio.genlayer.com/api",
  contractAddress: address,
  explorer: `https://explorer-studio.genlayer.com/address/${address}`,
  deployTxHash: deployment.deployTxHash,
  contractSha256: deployment.contractSha256,
  poster: poster.address,
  reproducer: reproducer.address,
  challenger: challenger.address,
  expectedOutputHash: EXPECTED_OUT_HASH,
  funding: {
    ...funding,
    fundedGenPerAccount: FUND_GEN,
    eoaBalanceBeforeWei: eoaBefore,
    eoaBalanceAfterWei: eoaAfter,
  },
  txs: { ...txs },
  deadZoneRetries,
  readbacks: {
    attempt0: attempt0Final,
    bounty0,
    reproducerCreditAfterReproducedWei: reproCredit0,
    reproducerReputationAfterReproduced: reproRep0,
    attempt1: attempt1Final,
    bounty1,
    attempt2: attempt2Final,
    bounty2,
    bounty3,
    totals,
    reputation: finalReputation,
    credits: finalCredits,
  },
  checkedAt: new Date().toISOString(),
};
// Guard the old evidence bug: every value in txs must be a 0x hash.
for (const [k, v] of Object.entries(evidence.txs)) {
  if (typeof v !== "string" || !/^0x[0-9a-fA-F]{64}$/.test(v)) {
    throw new Error(`evidence txs.${k} is not a transaction hash: ${String(v).slice(0, 80)}`);
  }
}
writeFileSync(path.join(root, "evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
console.log("Wrote evidence.json");
console.log("FLOW COMPLETE: #0 REPRODUCED + 40 GEN paid, #1 FAILED + 40 GEN refunded, #2 INCONCLUSIVE 10/30 GEN split paid, #3 cancelled + 40 GEN refunded");

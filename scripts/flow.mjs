/* End-to-end on-chain flow against an already-deployed ReproBounty contract.
 *
 * Usage:
 *   CONTRACT_ADDRESS=0x... node scripts/flow.mjs
 *   # Keys are ephemeral per run (Studionet is gasless); no key is written
 *   # to disk. Three roles use three ephemeral accounts: poster,
 *   * reproducer, challenger.
 *
 * Steps (10 transactions, minimum for both verdict paths + challenge):
 *   poster:    claim_demo_funds -> post_bounty #0 (4000 simulated mGEN)
 *   reproducer: submit_replication #0 (genuine output + complete log)
 *   poster:    evaluate_replication #0, round 1 -> EVALUATING, pending REPRODUCED
 *   challenger: challenge_replication #0
 *   reproducer: evaluate_replication #0, round 2 -> FINALIZED REPRODUCED,
 *              escrow released to reproducer
 *   poster:    post_bounty #1 (2000 simulated mGEN)
 *   reproducer: submit_replication #1 (wrong output text)
 *   poster:    evaluate_replication #1, round 1 -> EVALUATING, pending FAILED
 *              (deterministic hash mismatch; LLM scores cannot rescue it)
 *   poster:    finalize_replication #1 -> FINALIZED FAILED, escrow stays locked
 * Every step is read back via RPC. Writes evidence.json (tx hashes, final
 * status, read-back records). If an evaluation lands in the dead-score
 * zone (60-80), validators reject it, the attempt stays SUBMITTED, and
 * the script retries that evaluation once.
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

async function write(client, functionName, args, label) {
  const hash = await client.writeContract({ address, functionName, args, value: 0n, leaderOnly: false });
  await waitFinal(client, hash, label);
  return hash;
}

async function read(client, functionName, args) {
  const raw = await client.readContract({ address, functionName, args });
  if (typeof raw === "string" && (raw.startsWith("{") || raw.startsWith("["))) return JSON.parse(raw);
  return raw;
}

const GOOD_OUTPUT = "pi=3.14159";
const GOOD_LOG =
  "REPRO-START run reproduce.py --seed 7\n" +
  "step 1: load data ok\nstep 2: compute pi series ok\n" +
  "RESULT pi=3.14159 matches expected\nREPRO-END exit 0";
const CODE_HASH = sha256("reproduce.py v1");
const SPEC_HASH = sha256("spec: compute pi to 5 decimals");
const EXPECTED_OUT_HASH = sha256(GOOD_OUTPUT);
console.log("Expected output hash:", EXPECTED_OUT_HASH);

const txs = {};

// 1. Poster claims demo funds, posts bounty #0 (4000).
txs.claimTx = await write(posterClient, "claim_demo_funds", [], "claim_demo_funds");
console.log("Poster balance:", String(await read(posterClient, "get_balance", [poster.address])));
txs.postBounty0Tx = await write(
  posterClient, "post_bounty",
  [SPEC_HASH, "https://example.org/reproduce.py", CODE_HASH, EXPECTED_OUT_HASH, 4000n],
  "post_bounty#0"
);

// 2. Reproducer submits a genuine replication.
txs.submit0Tx = await write(
  reproClient, "submit_replication", [0n, CODE_HASH, GOOD_OUTPUT, GOOD_LOG],
  "submit_replication#0"
);
const attempt0 = await read(posterClient, "get_attempt", [0n]);
console.log("Attempt #0 output_hash:", attempt0.output_hash);
if (attempt0.output_hash !== EXPECTED_OUT_HASH) throw new Error("output_hash mismatch on read-back");

// 3. Evaluate round 1 (retry once if the scores land in the dead zone).
async function evaluateWithRetry(client, attemptId, label) {
  for (let attempt = 1; attempt <= 2; attempt++) {
    const hash = await write(client, "evaluate_replication", [attemptId], `${label} (try ${attempt})`);
    const state = await read(posterClient, "get_attempt", [attemptId]);
    console.log(`${label} state after try ${attempt}:`, state.status, "round", state.round, "pending", state.pending_verdict, "verdict", state.verdict);
    if (state.status === "EVALUATING" || state.status === "FINALIZED") return { hash, state };
    console.log(`${label}: still SUBMITTED (dead-zone scores rejected), retrying...`);
  }
  throw new Error(`${label} did not move out of SUBMITTED after 2 tries`);
}
const ev0 = await evaluateWithRetry(posterClient, 0n, "evaluate#0 round 1");
txs.evaluate0Round1Tx = ev0.hash;
if (ev0.state.pending_verdict !== "REPRODUCED") throw new Error(`Round 1 pending verdict is ${ev0.state.pending_verdict}, expected REPRODUCED`);

// 4. Challenger challenges; 5. round 2 finalizes directly.
txs.challenge0Tx = await write(challClient, "challenge_replication", [0n], "challenge#0");
const ev0b = await evaluateWithRetry(reproClient, 0n, "evaluate#0 round 2");
txs.evaluate0Round2Tx = ev0b.hash;
if (ev0b.state.status !== "FINALIZED" || ev0b.state.verdict !== "REPRODUCED") {
  throw new Error(`Round 2 did not finalize REPRODUCED: ${JSON.stringify(ev0b.state)}`);
}
const bounty0 = await read(posterClient, "get_bounty", [0n]);
const reproBalance = String(await read(posterClient, "get_balance", [reproducer.address]));
const reproRep = String(await read(posterClient, "get_reputation", [reproducer.address]));
console.log("Bounty #0 after round 2:", JSON.stringify(bounty0));
console.log("Reproducer balance:", reproBalance, "reputation:", reproRep);

// 6. Poster posts bounty #1 (2000). 7. Reproducer submits a WRONG output.
txs.postBounty1Tx = await write(
  posterClient, "post_bounty",
  [SPEC_HASH, "https://example.org/reproduce.py", CODE_HASH, EXPECTED_OUT_HASH, 2000n],
  "post_bounty#1"
);
const WRONG_OUTPUT = "pi=3.14000";
txs.submit1Tx = await write(
  reproClient, "submit_replication", [1n, CODE_HASH, WRONG_OUTPUT, GOOD_LOG],
  "submit_replication#1"
);
const attempt1 = await read(posterClient, "get_attempt", [1n]);
console.log("Attempt #1 output_hash:", attempt1.output_hash, "(expected:", EXPECTED_OUT_HASH + ")");
if (attempt1.output_hash === EXPECTED_OUT_HASH) throw new Error("wrong output hashed equal?!");

// 8. Evaluate #1 round 1 -> pending FAILED (deterministic hash mismatch).
const ev1 = await evaluateWithRetry(posterClient, 1n, "evaluate#1 round 1");
txs.evaluate1Round1Tx = ev1.hash;
if (ev1.state.pending_verdict !== "FAILED") throw new Error(`Round 1 pending verdict is ${ev1.state.pending_verdict}, expected FAILED`);
const attempt1After = await read(posterClient, "get_attempt", [1n]);
console.log("Attempt #1 witness:", JSON.stringify(attempt1After.witness));

// 9. Finalize #1 (no challenge) -> FINALIZED FAILED, escrow stays locked.
txs.finalize1Tx = await write(posterClient, "finalize_replication", [1n], "finalize#1");
const attempt1Final = await read(posterClient, "get_attempt", [1n]);
const bounty1 = await read(posterClient, "get_bounty", [1n]);
const reproRepFinal = String(await read(posterClient, "get_reputation", [reproducer.address]));
const posterBalanceFinal = String(await read(posterClient, "get_balance", [poster.address]));
console.log("Attempt #1 final:", JSON.stringify(attempt1Final));
console.log("Bounty #1 final:", JSON.stringify(bounty1));
console.log("Reproducer reputation final:", reproRepFinal, "poster balance final:", posterBalanceFinal);
if (attempt1Final.status !== "FINALIZED" || attempt1Final.verdict !== "FAILED") {
  throw new Error("Attempt #1 did not finalize FAILED");
}
if (bounty1.status !== "OPEN" || bounty1.escrow !== 2000) {
  throw new Error("Bounty #1 escrow should stay locked at 2000");
}

const evidence = {
  network: "Stable Studionet",
  chainId: 61999,
  rpcUrl: "https://studio.genlayer.com/api",
  contractAddress: address,
  explorer: `https://explorer-studio.genlayer.com/address/${address}`,
  poster: poster.address,
  reproducer: reproducer.address,
  challenger: challenger.address,
  expectedOutputHash: EXPECTED_OUT_HASH,
  txs: { ...txs, receiptStatus: "FINALIZED" },
  readbacks: {
    attempt0: ev0b.state,
    bounty0,
    reproducerBalanceAfterReproduced: reproBalance,
    reproducerReputationAfterReproduced: reproRep,
    attempt1: attempt1Final,
    bounty1,
    reproducerReputationFinal: reproRepFinal,
    posterBalanceFinal,
  },
  checkedAt: new Date().toISOString(),
};
writeFileSync(path.join(root, "evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
console.log("Wrote evidence.json");
console.log("FLOW COMPLETE: #0 REPRODUCED + released, #1 FAILED + escrow locked");

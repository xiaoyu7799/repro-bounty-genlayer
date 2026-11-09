/* Independent verification of the ReproBounty deployment + flow.
 * Reads every receipt and every piece of state fresh from the RPC and
 * compares against evidence.json. Exits non-zero on any mismatch.
 * The txs object in evidence.json must contain ONLY transaction
 * hashes; any non-hash value fails the check.
 * Usage: node scripts/verify.mjs
 */
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createClient, createAccount, generatePrivateKey } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { TransactionStatus } from "genlayer-js/types";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const deployment = JSON.parse(readFileSync(path.join(root, "deployment.json"), "utf-8"));
const evidence = JSON.parse(readFileSync(path.join(root, "evidence.json"), "utf-8"));
const address = deployment.contractAddress;
const client = createClient({ chain: studionet, account: createAccount(generatePrivateKey()) });

let checks = 0;
function check(name, cond, extra = "") {
  if (!cond) {
    console.error(`MISMATCH: ${name} ${extra}`);
    process.exit(1);
  }
  checks++;
  console.log(`  ok: ${name}${extra ? " — " + extra : ""}`);
}
function eq(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

// 0. evidence.json txs: only 0x transaction hashes, nothing else.
for (const [k, v] of Object.entries(evidence.txs)) {
  check(`evidence txs.${k} is a transaction hash`, typeof v === "string" && /^0x[0-9a-fA-F]{64}$/.test(v), String(v).slice(0, 20));
}

// 1. Deployed code == repo file at HEAD (gen_getContractCode, base64).
const cc = await client.request({ method: "gen_getContractCode", params: [address] });
const decoded = Buffer.from(cc, "base64").toString("utf-8");
const deployedSha = createHash("sha256").update(decoded).digest("hex");
const repoSha = createHash("sha256").update(readFileSync(path.join(root, "contracts", "repro_bounty.py"), "utf-8")).digest("hex");
check("deployed code SHA == repo file SHA", deployedSha === repoSha, deployedSha);
check("deployment.json SHA matches", deployment.contractSha256 === repoSha);

// 1b. Dead-zone retries (if any): FINALIZED, but they wrote nothing.
for (const r of evidence.deadZoneRetries || []) {
  const rec = await client.waitForTransactionReceipt({ hash: r.txHash, status: TransactionStatus.FINALIZED, retries: 10, interval: 3000 });
  check(`dead-zone retry ${r.label} try ${r.try} FINALIZED`, rec.status === 7 && rec.status_name === "FINALIZED", r.txHash.slice(0, 18) + "…");
}

// 2. Every tx receipt FINALIZED + MAJORITY_AGREE.
const allTxs = { deployTx: deployment.deployTxHash, ...evidence.txs };
for (const [label, hash] of Object.entries(allTxs)) {
  const r = await client.waitForTransactionReceipt({ hash, status: TransactionStatus.FINALIZED, retries: 10, interval: 3000 });
  check(`${label} FINALIZED`, r.status === 7 && r.status_name === "FINALIZED", hash.slice(0, 18) + "…");
  check(`${label} MAJORITY_AGREE`, r.result_name === "MAJORITY_AGREE", String(r.result_name));
}

// 3. State read-backs vs evidence.json.
async function read(fn, args) {
  const raw = await client.readContract({ address, functionName: fn, args });
  if (typeof raw === "string" && (raw.startsWith("{") || raw.startsWith("["))) return JSON.parse(raw);
  return raw;
}
const a0 = await read("get_attempt", [0n]);
const a1 = await read("get_attempt", [1n]);
const a2 = await read("get_attempt", [2n]);
const b0 = await read("get_bounty", [0n]);
const b1 = await read("get_bounty", [1n]);
const b2 = await read("get_bounty", [2n]);
const b3 = await read("get_bounty", [3n]);
check("attempt #0 == evidence", eq(a0, evidence.readbacks.attempt0));
check("attempt #1 == evidence", eq(a1, evidence.readbacks.attempt1));
check("attempt #2 == evidence", eq(a2, evidence.readbacks.attempt2));
check("bounty #0 == evidence", eq(b0, evidence.readbacks.bounty0));
check("bounty #1 == evidence", eq(b1, evidence.readbacks.bounty1));
check("bounty #2 == evidence", eq(b2, evidence.readbacks.bounty2));
check("bounty #3 == evidence", eq(b3, evidence.readbacks.bounty3));
check("attempt #0 DECIDED REPRODUCED, round 2", a0.status === "DECIDED" && a0.verdict === "REPRODUCED" && a0.round === 2);
check("attempt #0 first_verdict retained", a0.first_verdict === "REPRODUCED");
check("attempt #1 DECIDED FAILED, round 1", a1.status === "DECIDED" && a1.verdict === "FAILED" && a1.round === 1);
check("attempt #1 wrong-output hash != expected", a1.output_hash !== evidence.expectedOutputHash, a1.output_hash.slice(0, 16) + "…");
check("attempt #2 DECIDED INCONCLUSIVE, round 1", a2.status === "DECIDED" && a2.verdict === "INCONCLUSIVE" && a2.round === 1);
check("bounty #0 BOUNTY_CLOSED, escrow 0, winner = reproducer", b0.status === "BOUNTY_CLOSED" && String(b0.escrow_wei) === "0" && b0.winner === evidence.reproducer);
check("bounty #1 BOUNTY_REFUNDED, escrow 0", b1.status === "BOUNTY_REFUNDED" && String(b1.escrow_wei) === "0");
check("bounty #2 BOUNTY_CLOSED, split 10/30 GEN", b2.status === "BOUNTY_CLOSED" && String(b2.reproducer_share_wei) === "10000000000000000000" && String(b2.poster_share_wei) === "30000000000000000000");
check("bounty #3 BOUNTY_REFUNDED (cancelled), escrow 0", b3.status === "BOUNTY_REFUNDED" && String(b3.escrow_wei) === "0");
check("bounty count 4, attempt count 3",
  String(await read("get_bounty_count", [])) === "4" && String(await read("get_attempt_count", [])) === "3");

// 4. Money: totals invariant + EOA balances + reputation + credits.
const totals = await read("get_totals", []);
check("totals == evidence", eq(totals, evidence.readbacks.totals));
check("total_received 160 GEN", String(totals.total_received_wei) === "160000000000000000000");
check("total_paid_out 160 GEN", String(totals.total_paid_out_wei) === "160000000000000000000");
check("locked 0, credits 0, contract balance 0",
  String(totals.locked_wei) === "0" && String(totals.credits_total_wei) === "0" && String(totals.contract_balance_wei) === "0");
check("invariant total_in == total_out + locked + credits",
  BigInt(totals.total_received_wei) === BigInt(totals.total_paid_out_wei) + BigInt(totals.locked_wei) + BigInt(totals.credits_total_wei));
const posterEoa = (await client.getBalance({ address: evidence.poster })).toString();
const reproEoa = (await client.getBalance({ address: evidence.reproducer })).toString();
const challEoa = (await client.getBalance({ address: evidence.challenger })).toString();
check("poster EOA 9950 GEN (10000 - 160 + 110)", posterEoa === "9950000000000000000000", posterEoa);
check("reproducer EOA 10050 GEN (10000 + 40 + 10)", reproEoa === "10050000000000000000000", reproEoa);
check("challenger EOA 10000 GEN (unchanged)", challEoa === "10000000000000000000000", challEoa);
const reproRep = String(await read("get_reputation", [evidence.reproducer]));
const challRep = String(await read("get_reputation", [evidence.challenger]));
check("reproducer reputation 5 (0+10-5+0)", reproRep === "5", reproRep);
check("challenger reputation 0 (challenge failed, -5 floored at 0)", challRep === "0", challRep);
check("all credits 0",
  String(await read("get_credit", [evidence.poster])) === "0" &&
  String(await read("get_credit", [evidence.reproducer])) === "0" &&
  String(await read("get_credit", [evidence.challenger])) === "0");

console.log(`\nINDEPENDENT VERIFICATION: PASS (${checks} checks)`);

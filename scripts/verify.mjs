/* Independent verification of the ReproBounty deployment + flow.
 * Reads every receipt and every piece of state fresh from the RPC and
 * compares against evidence.json. Exits non-zero on any mismatch.
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

// 1. Deployed code == repo file at HEAD.
const code = await client.getContractCode(address);
const deployedSha = createHash("sha256").update(code).digest("hex");
const repoSha = createHash("sha256").update(readFileSync(path.join(root, "contracts", "repro_bounty.py"), "utf-8")).digest("hex");
check("deployed code SHA == repo file SHA", deployedSha === repoSha, deployedSha);
check("deployment.json SHA matches", deployment.contractSha256 === repoSha);

// 2. Every tx receipt FINALIZED + MAJORITY_AGREE (except deploy already checked).
const allTxs = { deployTx: deployment.deployTxHash, ...evidence.txs };
delete allTxs.receiptStatus;
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
const b0 = await read("get_bounty", [0n]);
const b1 = await read("get_bounty", [1n]);
check("attempt #0 == evidence", eq(a0, evidence.readbacks.attempt0));
check("attempt #1 == evidence", eq(a1, evidence.readbacks.attempt1));
check("bounty #0 == evidence", eq(b0, evidence.readbacks.bounty0));
check("bounty #1 == evidence", eq(b1, evidence.readbacks.bounty1));
check("attempt #0 FINALIZED REPRODUCED, round 2", a0.status === "FINALIZED" && a0.verdict === "REPRODUCED" && a0.round === 2);
check("attempt #0 scores 95/90/85 min 85", eq(a0.scores, { log_consistency: 95, output_plausibility: 90, code_fidelity: 85, min_score: 85 }));
check("attempt #0 first_verdict retained", a0.first_verdict === "REPRODUCED");
check("attempt #1 FINALIZED FAILED, round 1", a1.status === "FINALIZED" && a1.verdict === "FAILED" && a1.round === 1);
check("attempt #1 wrong-output hash != expected", a1.output_hash !== evidence.expectedOutputHash, a1.output_hash.slice(0, 16) + "…");
check("attempt #1 output_plausibility 12 (log/output disagree)", a1.scores.output_plausibility === 12);
check("bounty #0 CLOSED, escrow 0, winner = reproducer", b0.status === "CLOSED" && b0.escrow === 0 && b0.winner === evidence.reproducer);
check("bounty #1 OPEN, escrow still 2000", b1.status === "OPEN" && b1.escrow === 2000);
const reproBal = String(await read("get_balance", [evidence.reproducer]));
const posterBal = String(await read("get_balance", [evidence.poster]));
const reproRep = String(await read("get_reputation", [evidence.reproducer]));
const challRep = String(await read("get_reputation", [evidence.challenger]));
check("reproducer balance 4000", reproBal === "4000", reproBal);
check("poster balance 4000", posterBal === "4000", posterBal);
check("reproducer reputation 105 (100+10-5)", reproRep === "105", reproRep);
check("challenger reputation 95 (challenge failed: verdicts equal)", challRep === "95", challRep);
check("bounty count 2, attempt count 2",
  String(await read("get_bounty_count", [])) === "2" && String(await read("get_attempt_count", [])) === "2");

console.log(`\nINDEPENDENT VERIFICATION: PASS (${checks} checks)`);

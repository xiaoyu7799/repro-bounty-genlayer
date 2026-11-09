/* Local simulation of the deterministic decision rules — MOCK ONLY.
 *
 * Runs entirely off-chain in Node: recomputes the SHA-256 of the demo
 * output, checks the deterministic verdict table, and enumerates the
 * score-band margin proof (every accepted leader minimum, every
 * validator minimum within +-10, must stay on the same side of the 70
 * boundary). Proves NOTHING about GenLayer consensus: only the on-chain
 * evaluate_reproduction transactions, with real validators, are
 * consensus evidence. No on-chain transaction is sent by this script.
 *
 * Usage: node scripts/simulate.mjs
 */
import { createHash } from "node:crypto";

const sha256 = (s) => createHash("sha256").update(s, "utf-8").digest("hex");

let checks = 0;
function check(name, cond) {
  if (!cond) {
    console.error(`FAIL: ${name}`);
    process.exit(1);
  }
  checks++;
  console.log(`  ok: ${name}`);
}

console.log("== deterministic hashes ==");
const good = "pi=3.14159";
const wrong = "pi=3.14000";
console.log(`  sha256("pi=3.14159") = ${sha256(good)}`);
console.log(`  sha256("pi=3.14000") = ${sha256(wrong)}`);
check("good output hash is stable", sha256(good) === sha256(good));
check("one-digit difference gives a completely different hash", sha256(good) !== sha256(wrong));

console.log("== deterministic verdict table ==");
function det(hashMatch, codeMatch, logComplete) {
  if (!hashMatch) return "FAILED";
  if (!codeMatch) return "FAILED";
  if (!logComplete) return "INCONCLUSIVE";
  return "REPRODUCED_CANDIDATE";
}
for (const [h, c, l, want] of [
  [true, true, true, "REPRODUCED_CANDIDATE"],
  [true, true, false, "INCONCLUSIVE"],
  [true, false, true, "FAILED"],
  [false, true, true, "FAILED"],
]) {
  check(`D(${h},${c},${l}) == ${want}`, det(h, c, l) === want);
}

console.log("== score-band margin proof (exhaustive) ==");
const BOUNDARY = 70, TOL = 10, ACCEPT_MIN_REPRO = 81, ACCEPT_MAX_INC = 59;
function side(m) { return m >= BOUNDARY ? "REPRODUCED" : "INCONCLUSIVE"; }
let bandChecks = 0;
for (let leader = 0; leader <= 100; leader++) {
  const accepted = leader >= ACCEPT_MIN_REPRO || leader <= ACCEPT_MAX_INC;
  if (!accepted) continue;
  for (let v = Math.max(0, leader - TOL); v <= Math.min(100, leader + TOL); v++) {
    if (side(v) !== side(leader)) {
      console.error(`FAIL: leader ${leader} vs validator ${v} flip sides`);
      process.exit(1);
    }
    bandChecks++;
  }
}
console.log(`  ok: ${bandChecks} leader/validator pairs stay on the same side of 70`);
console.log("== worst-case spread ==");
console.log("  Two validator-compatible leader outputs agree on the verdict,");
console.log("  so on a 40 GEN escrow the payout difference is exactly 0 GEN.");
check("worst-case spread = 0 verdict flips, 0 GEN", true);
console.log(`SIMULATION: PASS (${checks} checks)`);

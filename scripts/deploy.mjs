/* Deploy ReproBounty to Stable Studionet (chain 61999) only.
 *
 * Usage:
 *   GENLAYER_PRIVATE_KEY=0x... node scripts/deploy.mjs
 *   # or, for a throwaway deployer (Studionet is gasless, 0 GEN):
 *   node scripts/deploy.mjs
 *
 * The private key is NEVER written to disk or to deployment.json. If no
 * key is supplied, an ephemeral key is generated for this run only; the
 * contract is permissionless, so losing that key loses nothing.
 *
 * After deploy, the deployed code is read back via gen_getContractCode
 * (base64), decoded, and SHA-256-compared with the repository source
 * file. A FINALIZED receipt alone is NOT accepted as proof: the code
 * hash must match byte for byte.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createClient, createAccount, generatePrivateKey } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { TransactionStatus } from "genlayer-js/types";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const codePath = path.join(root, "contracts", "repro_bounty.py");
const code = readFileSync(codePath, "utf-8");
const codeSha = createHash("sha256").update(code).digest("hex");
console.log("Source SHA-256:", codeSha);

const suppliedKey = process.env.GENLAYER_PRIVATE_KEY;
const privateKey = suppliedKey || generatePrivateKey();
if (!suppliedKey) {
  console.log("No GENLAYER_PRIVATE_KEY supplied: using an ephemeral deployer key for this run only.");
}
const account = createAccount(privateKey);
console.log("Deployer:", account.address);
console.log("Network: Stable Studionet, chain 61999, https://studio.genlayer.com/api");

const STATUS = { 0: "UNINITIALIZED", 1: "PENDING", 2: "PROPOSING", 3: "COMMITTING", 4: "REVEALING", 5: "ACCEPTED", 6: "UNDETERMINED", 7: "FINALIZED", 8: "CANCELED" };
const client = createClient({ chain: studionet, account });
const txHash = await client.deployContract({ code, args: [], leaderOnly: false });
console.log("Deploy tx:", txHash);

const receipt = await client.waitForTransactionReceipt({
  hash: txHash,
  status: TransactionStatus.FINALIZED,
  retries: 180,
  interval: 5000,
});
const receiptStatus = receipt.statusName ?? STATUS[receipt.status] ?? String(receipt.status ?? "");
console.log("Receipt status:", receiptStatus);
if (receiptStatus !== "FINALIZED") throw new Error(`Deploy did not finalize: ${receiptStatus}`);

const address =
  receipt?.data?.contract_address ??
  receipt?.txDataDecoded?.contractAddress ??
  receipt?.contractAddress ??
  null;
if (!address) {
  console.log("Full receipt (no private key):", JSON.stringify(receipt, null, 2).slice(0, 4000));
  throw new Error("Could not find contract address in deploy receipt");
}
console.log("Contract address:", address);

// Read the deployed code back and compare SHA-256 with the source file.
const cc = await client.request({ method: "gen_getContractCode", params: [address] });
if (typeof cc !== "string" || cc.length === 0) throw new Error("gen_getContractCode returned nothing");
const decoded = Buffer.from(cc, "base64").toString("utf-8");
const deployedSha = createHash("sha256").update(decoded).digest("hex");
console.log("Deployed code SHA-256:", deployedSha);
console.log("Deployed code == source file byte for byte:", decoded === code);
if (decoded !== code) throw new Error("DEPLOYED CODE DOES NOT MATCH SOURCE FILE");

const deployment = {
  network: "Stable Studionet",
  chainId: 61999,
  rpcUrl: "https://studio.genlayer.com/api",
  explorer: `https://explorer-studio.genlayer.com/address/${address}`,
  studio: `https://studio.genlayer.com/?import-contract=${address}`,
  contractAddress: address,
  deployTxHash: txHash,
  deployer: account.address,
  contractFile: "contracts/repro_bounty.py",
  contractSha256: codeSha,
  deployedCodeSha256: deployedSha,
  deployedAt: new Date().toISOString(),
  receiptStatus,
};
writeFileSync(path.join(root, "deployment.json"), JSON.stringify(deployment, null, 2) + "\n");
console.log("Wrote deployment.json");
console.log("DEPLOY OK");

# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""ReproBounty: a research-replication bounty primitive for GenLayer.

A poster locks a bounty in real testnet GEN behind a published
experiment spec. A reproducer re-runs the code and submits the run log
plus the actual output text. Validator consensus decides whether the
replication genuinely reproduced the claimed result: REPRODUCED /
FAILED / INCONCLUSIVE. The bounty is paid out only through pull
payments: finalization records a credit in wei, and the beneficiary
calls withdraw_payout() to receive real GEN. No push payment ever
happens at finalization time.

Money (real GEN on Stable Studionet, Chain ID 61999, 1 GEN = 10^18 wei,
faucet-funded testnet GEN, zero cash cost):
- post_bounty is payable: the GEN sent with the call is the bounty and
  is locked in the contract. The amount must be divisible by 4 wei so
  the INCONCLUSIVE split is exact.
- REPRODUCED: the full escrow is credited to the reproducer.
- FAILED: the full escrow is credited back to the poster.
- INCONCLUSIVE: 25% is credited to the reproducer, 75% back to the
  poster.
- cancel_bounty (poster only, before any decision is pending) credits
  the full escrow back to the poster.
- withdraw_payout() zeroes the caller's credit first, then transfers
  the GEN to the caller's address.
- Invariant: total_received_wei == total_paid_out_wei + locked_wei +
  credits_total_wei, and the contract balance equals locked_wei +
  credits_total_wei. See get_totals().

Reputation starts at 0 for every address: +10 for a REPRODUCED
replication, -5 for FAILED (floored at 0), no change for
INCONCLUSIVE. Challenging costs no GEN: a failed challenge (the
second verdict equals the first) costs the challenger 5 reputation,
a successful one gains 5.

Bounty states: OPEN -> REPRODUCTION_SUBMITTED ->
VERDICT_REPRODUCED / VERDICT_FAILED / VERDICT_INCONCLUSIVE ->
BOUNTY_CLOSED / BOUNTY_REFUNDED. Attempt states: SUBMITTED ->
AWAITING_DECISION -> DECIDED.

Decision rule (see docs/mechanism.md for the worst-case spread proof):
- Deterministic, exact: the output hash is computed on-chain from the
  submitted text with pure-Python SHA-256 and must equal the expected
  hash exactly; the code hash must match exactly; the run log must
  contain both REPRO-START and REPRO-END markers. No tolerance, no
  "close enough": a different-but-close hash is FAILED.
- LLM judgement decides only the subjective part (does the log read as
  a genuine run): three integer scores 0-100, verdict from the minimum
  score with a single boundary at 70 and a required margin of 11
  (accepted leader minima are >= 81 or <= 59; 60-80 is a dead zone
  that validators reject). Per-score tolerance is 10, so any
  validator-compatible score set stays on the same side of the
  boundary: worst-case spread is 0 verdict flips, 0 GEN difference.
"""

import json

from genlayer import *


@gl.evm.contract_interface
class _Recipient:
    class View:
        pass

    class Write:
        pass


# ==============================================================================
# 1. PURE-PYTHON SHA-256 (no dependency on unverified stdlib hashlib in GenVM)
# ==============================================================================

_K256 = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
]


def _rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF


def pure_sha256_hex(msg_str: str) -> str:
    data = bytearray(msg_str.encode("utf-8"))
    bit_len = len(data) * 8
    data.append(0x80)
    while (len(data) % 64) != 56:
        data.append(0x00)
    for i in range(7, -1, -1):
        data.append((bit_len >> (i * 8)) & 0xFF)
    h = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    ]
    for offset in range(0, len(data), 64):
        w = [0] * 64
        for i in range(16):
            j = offset + i * 4
            w[i] = (data[j] << 24) | (data[j + 1] << 16) | (data[j + 2] << 8) | data[j + 3]
        for i in range(16, 64):
            s0 = _rotr(w[i - 15], 7) ^ _rotr(w[i - 15], 18) ^ (w[i - 15] >> 3)
            s1 = _rotr(w[i - 2], 17) ^ _rotr(w[i - 2], 19) ^ (w[i - 2] >> 10)
            w[i] = (w[i - 16] + s0 + w[i - 7] + s1) & 0xFFFFFFFF
        a, b, c, d, e, f, g, hh = h
        for i in range(64):
            s1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
            ch = (e & f) ^ ((~e & 0xFFFFFFFF) & g)
            temp1 = (hh + s1 + ch + _K256[i] + w[i]) & 0xFFFFFFFF
            s0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
            maj = (a & b) ^ (a & c) ^ (b & c)
            temp2 = (s0 + maj) & 0xFFFFFFFF
            hh, g, f, e, d, c, b, a = g, f, e, (d + temp1) & 0xFFFFFFFF, c, b, a, (temp1 + temp2) & 0xFFFFFFFF
        h = [(h[idx] + val) & 0xFFFFFFFF for idx, val in enumerate([a, b, c, d, e, f, g, hh])]
    hex_chars = "0123456789abcdef"
    out = []
    for word in h:
        for shift in (28, 24, 20, 16, 12, 8, 4, 0):
            out.append(hex_chars[(word >> shift) & 0xF])
    return "".join(out)


# ==============================================================================
# 2. CONSTANTS AND DETERMINISTIC DECISION RULES
# ==============================================================================

SCORE_TOLERANCE = 10
VERDICT_BOUNDARY = 70
MARGIN = 11
ACCEPT_MIN_REPRODUCED = 81   # VERDICT_BOUNDARY + MARGIN
ACCEPT_MAX_INCONCLUSIVE = 59  # VERDICT_BOUNDARY - MARGIN - 1
MIN_LOG_LEN = 40
MAX_OUTPUT_LEN = 2000
MAX_LOG_LEN = 4000
MAX_REF_LEN = 200
# INCONCLUSIVE split: reproducer 1/4, poster 3/4 of the escrow (exact in
# wei because post_bounty requires the bounty to be divisible by 4 wei).
INCONCLUSIVE_REPRODUCER_NUM = 1
INCONCLUSIVE_SPLIT_DEN = 4


def _is_hex64(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    for ch in value:
        if ch not in "0123456789abcdef":
            return False
    return True


def _deterministic_verdict(hash_match: bool, code_match: bool, log_complete: bool) -> str:
    if not hash_match:
        return "FAILED"
    if not code_match:
        return "FAILED"
    if not log_complete:
        return "INCONCLUSIVE"
    return "REPRODUCED_CANDIDATE"


def _scores_verdict(min_score: int) -> str:
    if min_score >= ACCEPT_MIN_REPRODUCED:
        return "REPRODUCED"
    return "INCONCLUSIVE"


def _combine_verdict(deterministic: str, scores_verdict: str) -> str:
    if deterministic == "FAILED":
        return "FAILED"
    if deterministic == "INCONCLUSIVE":
        return "INCONCLUSIVE"
    return scores_verdict


class ReproBounty(gl.Contract):
    bounties: TreeMap[u256, str]
    attempts: TreeMap[u256, str]
    credits: TreeMap[str, u256]
    reputation: TreeMap[str, u256]
    next_bounty_id: u256
    next_attempt_id: u256
    attempt_ids: DynArray[u256]
    total_received: u256
    total_paid_out: u256
    locked_wei: u256
    credits_total: u256

    def __init__(self):
        self.next_bounty_id = u256(0)
        self.next_attempt_id = u256(0)
        self.total_received = u256(0)
        self.total_paid_out = u256(0)
        self.locked_wei = u256(0)
        self.credits_total = u256(0)

    # -- deterministic helpers -------------------------------------------

    def _sender(self) -> str:
        return str(gl.message.sender_address)

    def _map_int(self, mapping, key, default: int) -> int:
        if key in mapping:
            return int(mapping[key])
        return default

    def _rep(self, address: str) -> int:
        return self._map_int(self.reputation, address, 0)

    def _set_rep(self, address: str, value: int) -> None:
        if value < 0:
            value = 0
        self.reputation[address] = u256(value)

    def _adjust_rep(self, address: str, delta: int) -> None:
        self._set_rep(address, self._rep(address) + delta)

    def _credit(self, address: str, amount_wei: int) -> None:
        prev = self._map_int(self.credits, address, 0)
        self.credits[address] = u256(prev + amount_wei)
        self.credits_total = self.credits_total + u256(amount_wei)

    def _load_bounty(self, bounty_id: u256) -> dict:
        if bounty_id not in self.bounties:
            raise gl.vm.UserError("EXPECTED: bounty_not_found")
        return json.loads(self.bounties[bounty_id])

    def _save_bounty(self, bounty: dict) -> None:
        self.bounties[u256(bounty["id"])] = json.dumps(bounty)

    def _load_attempt(self, attempt_id: u256) -> dict:
        if attempt_id not in self.attempts:
            raise gl.vm.UserError("EXPECTED: attempt_not_found")
        return json.loads(self.attempts[attempt_id])

    def _save_attempt(self, attempt: dict) -> None:
        self.attempts[u256(attempt["id"])] = json.dumps(attempt)

    def _deterministic_facts(self, bounty: dict, attempt: dict) -> dict:
        hash_match = attempt["output_hash"] == bounty["expected_output_hash"]
        code_match = attempt["code_hash"] == bounty["expected_code_hash"]
        log = attempt["run_log"]
        log_complete = ("REPRO-START" in log) and ("REPRO-END" in log) and len(log) >= MIN_LOG_LEN
        return {
            "hash_match": hash_match,
            "code_match": code_match,
            "log_complete": log_complete,
            "deterministic_verdict": _deterministic_verdict(hash_match, code_match, log_complete),
        }

    def _apply_final_verdict(self, bounty: dict, attempt: dict, verdict: str) -> None:
        attempt["status"] = "DECIDED"
        attempt["verdict"] = verdict
        attempt["pending_verdict"] = None
        reproducer = attempt["reproducer"]
        poster = bounty["poster"]
        escrow = int(bounty["escrow_wei"])
        self.locked_wei = self.locked_wei - u256(escrow)
        bounty["escrow_wei"] = 0
        if verdict == "REPRODUCED":
            bounty["status"] = "VERDICT_REPRODUCED"
            bounty["winner"] = reproducer
            bounty["reproducer_share_wei"] = escrow
            bounty["poster_share_wei"] = 0
            self._credit(reproducer, escrow)
            self._adjust_rep(reproducer, 10)
        elif verdict == "FAILED":
            bounty["status"] = "VERDICT_FAILED"
            bounty["reproducer_share_wei"] = 0
            bounty["poster_share_wei"] = escrow
            self._credit(poster, escrow)
            self._adjust_rep(reproducer, -5)
        else:  # INCONCLUSIVE: 25% to the reproducer, 75% back to the poster.
            reproducer_share = (escrow * INCONCLUSIVE_REPRODUCER_NUM) // INCONCLUSIVE_SPLIT_DEN
            poster_share = escrow - reproducer_share
            bounty["status"] = "VERDICT_INCONCLUSIVE"
            bounty["reproducer_share_wei"] = reproducer_share
            bounty["poster_share_wei"] = poster_share
            self._credit(reproducer, reproducer_share)
            self._credit(poster, poster_share)
        if attempt["round"] == 2 and attempt["first_verdict"] is not None:
            challenger = attempt["challenger"]
            if challenger:
                if verdict == attempt["first_verdict"]:
                    self._adjust_rep(challenger, -5)
                else:
                    self._adjust_rep(challenger, 5)

    # -- writes ------------------------------------------------------------

    @gl.public.write.payable
    def post_bounty(self, spec_hash: str, code_ref: str, expected_code_hash: str,
                    expected_output_hash: str) -> u256:
        if not _is_hex64(spec_hash):
            raise gl.vm.UserError("EXPECTED: spec_hash_must_be_64_lowercase_hex")
        if not _is_hex64(expected_code_hash):
            raise gl.vm.UserError("EXPECTED: expected_code_hash_must_be_64_lowercase_hex")
        if not _is_hex64(expected_output_hash):
            raise gl.vm.UserError("EXPECTED: expected_output_hash_must_be_64_lowercase_hex")
        if not isinstance(code_ref, str) or len(code_ref) < 1 or len(code_ref) > MAX_REF_LEN:
            raise gl.vm.UserError("EXPECTED: code_ref_must_be_1_to_200_chars")
        value = gl.message.value
        if value == u256(0):
            raise gl.vm.UserError("EXPECTED: bounty_must_send_gen")
        if int(value) % INCONCLUSIVE_SPLIT_DEN != 0:
            raise gl.vm.UserError("EXPECTED: bounty_must_be_divisible_by_4_wei")
        sender = self._sender()
        bounty_id = self.next_bounty_id
        self.next_bounty_id = bounty_id + u256(1)
        bounty = {
            "id": int(bounty_id),
            "poster": sender,
            "spec_hash": spec_hash,
            "code_ref": code_ref,
            "expected_code_hash": expected_code_hash,
            "expected_output_hash": expected_output_hash,
            "amount_wei": int(value),
            "escrow_wei": int(value),
            "status": "OPEN",
            "winner": None,
            "reproducer": None,
            "reproducer_share_wei": 0,
            "poster_share_wei": 0,
        }
        self.total_received = self.total_received + value
        self.locked_wei = self.locked_wei + value
        self._save_bounty(bounty)
        return bounty_id

    @gl.public.write
    def submit_reproduction(self, bounty_id: u256, code_hash: str,
                            output_text: str, run_log: str) -> u256:
        bounty = self._load_bounty(bounty_id)
        if bounty["status"] != "OPEN":
            raise gl.vm.UserError("EXPECTED: bounty_not_open")
        if not _is_hex64(code_hash):
            raise gl.vm.UserError("EXPECTED: code_hash_must_be_64_lowercase_hex")
        if not isinstance(output_text, str) or len(output_text) < 1 or len(output_text) > MAX_OUTPUT_LEN:
            raise gl.vm.UserError("EXPECTED: output_text_must_be_1_to_2000_chars")
        if not isinstance(run_log, str) or len(run_log) < 1 or len(run_log) > MAX_LOG_LEN:
            raise gl.vm.UserError("EXPECTED: run_log_must_be_1_to_4000_chars")
        attempt_id = self.next_attempt_id
        self.next_attempt_id = attempt_id + u256(1)
        attempt = {
            "id": int(attempt_id),
            "bounty_id": int(bounty_id),
            "reproducer": self._sender(),
            "code_hash": code_hash,
            "output_text": output_text,
            "output_hash": pure_sha256_hex(output_text),
            "run_log": run_log,
            "status": "SUBMITTED",
            "round": 0,
            "pending_verdict": None,
            "verdict": None,
            "first_verdict": None,
            "scores": None,
            "challenged": False,
            "challenger": None,
            "witness": None,
        }
        self.attempt_ids.append(attempt_id)
        bounty["status"] = "REPRODUCTION_SUBMITTED"
        bounty["reproducer"] = attempt["reproducer"]
        self._save_bounty(bounty)
        self._save_attempt(attempt)
        return attempt_id

    @gl.public.write
    def evaluate_reproduction(self, attempt_id: u256) -> str:
        attempt = self._load_attempt(attempt_id)
        bounty = self._load_bounty(u256(attempt["bounty_id"]))
        if bounty["status"] != "REPRODUCTION_SUBMITTED":
            raise gl.vm.UserError("EXPECTED: bounty_not_awaiting_reproduction_verdict")
        if attempt["status"] == "DECIDED":
            raise gl.vm.UserError("EXPECTED: attempt_already_decided")
        if attempt["status"] == "SUBMITTED":
            round_no = 1
        elif attempt["status"] == "AWAITING_DECISION" and attempt["challenged"] and attempt["round"] == 1:
            round_no = 2
        else:
            raise gl.vm.UserError("EXPECTED: attempt_not_ready_for_evaluation")
        facts = self._deterministic_facts(bounty, attempt)
        run_log = attempt["run_log"]
        output_text = attempt["output_text"]

        def judge() -> dict:
            prompt = (
                "You judge one question only: does this run log read as a genuine "
                "execution of the claimed code producing the submitted output? "
                "Hash and code equality have already been checked by code; score "
                "only the credibility of the log itself. "
                "Score decisively: clearly genuine evidence 85-100 on every dimension; "
                "anything doubtful 0-59. Never return a score from 60 to 80 inclusive. "
                "Return JSON only with integer scores 0-100: log_consistency "
                "(the log reads as a real sequential run: start, steps, result, no "
                "contradiction), output_plausibility (the result reported in the log "
                "agrees with the submitted output text), code_fidelity (the log "
                "references the steps and files the claimed code would produce). "
                "Deterministic facts already established by code: hash_match="
                + ("true" if facts["hash_match"] else "false")
                + ", code_match=" + ("true" if facts["code_match"] else "false")
                + ", log_complete=" + ("true" if facts["log_complete"] else "false")
                + ". Submitted output text: " + output_text[:500]
                + ". Run log: " + run_log[:2000]
            )
            parsed = gl.nondet.exec_prompt(prompt, response_format="json")
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            values = []
            for key in ("log_consistency", "output_plausibility", "code_fidelity"):
                value = str(parsed[key])
                if not value.isdigit() or int(value) > 100:
                    raise Exception("INVALID_SCORE_PENDING_RETRY")
                values.append(int(value))
            min_score = values[0]
            if values[1] < min_score:
                min_score = values[1]
            if values[2] < min_score:
                min_score = values[2]
            if min_score >= ACCEPT_MIN_REPRODUCED:
                scores_verdict = "REPRODUCED"
            elif min_score <= ACCEPT_MAX_INCONCLUSIVE:
                scores_verdict = "INCONCLUSIVE"
            else:
                raise Exception("SCORES_IN_DEAD_ZONE_PENDING_RETRY")
            final_verdict = _combine_verdict(facts["deterministic_verdict"], scores_verdict)
            return {
                "status": "OK",
                "hash_match": "true" if facts["hash_match"] else "false",
                "code_match": "true" if facts["code_match"] else "false",
                "log_complete": "true" if facts["log_complete"] else "false",
                "deterministic_verdict": facts["deterministic_verdict"],
                "log_consistency": str(values[0]),
                "output_plausibility": str(values[1]),
                "code_fidelity": str(values[2]),
                "min_score": str(min_score),
                "scores_verdict": scores_verdict,
                "verdict": final_verdict,
            }

        def validate(leader) -> bool:
            if isinstance(leader, gl.vm.UserError):
                try:
                    judge()
                except Exception:
                    return True
                return False
            if not isinstance(leader, gl.vm.Return):
                return False
            proposed = leader.calldata
            if not isinstance(proposed, dict):
                return False
            try:
                own = judge()
            except Exception:
                return False
            # Exact agreement on every deterministic fact.
            for key in ("status", "hash_match", "code_match", "log_complete",
                        "deterministic_verdict", "scores_verdict", "verdict"):
                if proposed.get(key) != own[key]:
                    return False
            # Per-score tolerance 10; dead zone rejected on the leader's own min.
            try:
                leader_min = int(proposed["min_score"])
                own_scores = [int(own[k]) for k in ("log_consistency", "output_plausibility", "code_fidelity")]
                leader_scores = [int(proposed[k]) for k in ("log_consistency", "output_plausibility", "code_fidelity")]
            except Exception:
                return False
            if not (0 <= leader_min <= 100):
                return False
            if leader_min != min(leader_scores):
                return False
            if not (leader_min >= ACCEPT_MIN_REPRODUCED or leader_min <= ACCEPT_MAX_INCONCLUSIVE):
                return False
            for leader_v, own_v in zip(leader_scores, own_scores):
                if not (0 <= leader_v <= 100) or abs(leader_v - own_v) > SCORE_TOLERANCE:
                    return False
            # The leader's verdict must be exactly the combination rule
            # applied to the leader's own scores and the deterministic facts.
            if proposed.get("scores_verdict") != _scores_verdict(leader_min):
                return False
            if proposed.get("verdict") != _combine_verdict(own["deterministic_verdict"], proposed["scores_verdict"]):
                return False
            return True

        result = gl.vm.run_nondet_unsafe(judge, validate)
        verdict = result["verdict"]
        attempt["scores"] = {
            "log_consistency": int(result["log_consistency"]),
            "output_plausibility": int(result["output_plausibility"]),
            "code_fidelity": int(result["code_fidelity"]),
            "min_score": int(result["min_score"]),
        }
        if result["scores_verdict"] == "REPRODUCED" and facts["deterministic_verdict"] != "REPRODUCED_CANDIDATE":
            attempt["witness"] = {
                "kind": "llm_vs_deterministic",
                "llm_verdict": "REPRODUCED",
                "deterministic_verdict": facts["deterministic_verdict"],
                "note": "Scores judged the log genuine while the deterministic check did not; deterministic verdict stands.",
            }
        if round_no == 1:
            attempt["status"] = "AWAITING_DECISION"
            attempt["round"] = 1
            attempt["pending_verdict"] = verdict
            self._save_attempt(attempt)
        else:
            attempt["first_verdict"] = attempt["pending_verdict"]
            attempt["round"] = 2
            self._apply_final_verdict(bounty, attempt, verdict)
            self._save_bounty(bounty)
            self._save_attempt(attempt)
        return json.dumps({"attempt_id": int(attempt_id), "round": round_no, "verdict": verdict, "status": attempt["status"]})

    @gl.public.write
    def challenge_reproduction(self, attempt_id: u256) -> str:
        attempt = self._load_attempt(attempt_id)
        if attempt["status"] != "AWAITING_DECISION" or attempt["round"] != 1 or attempt["challenged"]:
            raise gl.vm.UserError("EXPECTED: attempt_not_open_to_challenge")
        sender = self._sender()
        if sender == attempt["reproducer"]:
            raise gl.vm.UserError("EXPECTED: reproducer_cannot_challenge_own_attempt")
        attempt["challenged"] = True
        attempt["challenger"] = sender
        self._save_attempt(attempt)
        return json.dumps({"attempt_id": int(attempt_id), "challenger": sender, "status": "AWAITING_DECISION"})

    @gl.public.write
    def finalize_reproduction(self, attempt_id: u256) -> str:
        attempt = self._load_attempt(attempt_id)
        bounty = self._load_bounty(u256(attempt["bounty_id"]))
        if attempt["status"] != "AWAITING_DECISION" or attempt["round"] != 1:
            raise gl.vm.UserError("EXPECTED: attempt_not_awaiting_finalize")
        if attempt["challenged"]:
            raise gl.vm.UserError("EXPECTED: challenged_attempt_must_be_reevaluated")
        if attempt["pending_verdict"] is None:
            raise gl.vm.UserError("EXPECTED: no_pending_verdict")
        verdict = attempt["pending_verdict"]
        self._apply_final_verdict(bounty, attempt, verdict)
        self._save_bounty(bounty)
        self._save_attempt(attempt)
        return json.dumps({"attempt_id": int(attempt_id), "verdict": verdict, "status": "DECIDED"})

    @gl.public.write
    def cancel_bounty(self, bounty_id: u256) -> str:
        bounty = self._load_bounty(bounty_id)
        if bounty["status"] not in ("OPEN", "REPRODUCTION_SUBMITTED"):
            raise gl.vm.UserError("EXPECTED: bounty_not_cancellable")
        if self._sender() != bounty["poster"]:
            raise gl.vm.UserError("EXPECTED: only_poster_can_cancel")
        for attempt_id in self.attempt_ids:
            attempt = json.loads(self.attempts[attempt_id])
            if int(attempt["bounty_id"]) == int(bounty_id) and attempt["status"] == "AWAITING_DECISION":
                raise gl.vm.UserError("EXPECTED: attempt_under_evaluation")
        escrow = int(bounty["escrow_wei"])
        poster = bounty["poster"]
        self.locked_wei = self.locked_wei - u256(escrow)
        bounty["escrow_wei"] = 0
        bounty["status"] = "BOUNTY_REFUNDED"
        bounty["poster_share_wei"] = escrow
        self._credit(poster, escrow)
        self._save_bounty(bounty)
        return json.dumps({"bounty_id": int(bounty_id), "status": "BOUNTY_REFUNDED", "refunded_wei": escrow})

    @gl.public.write
    def withdraw_payout(self) -> str:
        sender = self._sender()
        if sender not in self.credits:
            raise gl.vm.UserError("EXPECTED: no_credit")
        amount = self.credits[sender]
        if amount == u256(0):
            raise gl.vm.UserError("EXPECTED: no_credit")
        # Zero the credit BEFORE the transfer: a failed child message
        # cannot pay the same credit twice.
        self.credits[sender] = u256(0)
        self.credits_total = self.credits_total - amount
        self.total_paid_out = self.total_paid_out + amount
        _Recipient(Address(sender)).emit_transfer(value=amount)
        # Close out any bounty whose payout shares are now fully paid.
        index = 0
        total_bounties = int(self.next_bounty_id)
        while index < total_bounties:
            bounty = self._load_bounty(u256(index))
            if bounty["status"] in ("VERDICT_REPRODUCED", "VERDICT_FAILED", "VERDICT_INCONCLUSIVE"):
                reproducer = bounty["reproducer"]
                poster = bounty["poster"]
                reproducer_done = int(bounty["reproducer_share_wei"]) == 0 or (
                    reproducer is not None and self._map_int(self.credits, reproducer, 0) == 0)
                poster_done = int(bounty["poster_share_wei"]) == 0 or self._map_int(self.credits, poster, 0) == 0
                if reproducer_done and poster_done:
                    if bounty["status"] == "VERDICT_FAILED":
                        bounty["status"] = "BOUNTY_REFUNDED"
                    else:
                        bounty["status"] = "BOUNTY_CLOSED"
                    self._save_bounty(bounty)
            index += 1
        return json.dumps({
            "sender": sender,
            "withdrawn_wei": int(amount),
            "total_paid_out_wei": int(self.total_paid_out),
            "contract_balance_wei": int(self.balance),
        })

    # -- views -------------------------------------------------------------

    @gl.public.view
    def get_bounty(self, bounty_id: u256) -> str:
        return json.dumps(self._load_bounty(bounty_id))

    @gl.public.view
    def get_attempt(self, attempt_id: u256) -> str:
        return json.dumps(self._load_attempt(attempt_id))

    @gl.public.view
    def get_bounty_count(self) -> u256:
        return u256(int(self.next_bounty_id))

    @gl.public.view
    def get_attempt_count(self) -> u256:
        return u256(int(self.next_attempt_id))

    @gl.public.view
    def get_credit(self, address: str) -> u256:
        return u256(self._map_int(self.credits, address, 0))

    @gl.public.view
    def get_reputation(self, address: str) -> u256:
        return u256(self._rep(address))

    @gl.public.view
    def get_totals(self) -> str:
        return json.dumps(
            {
                "total_received_wei": int(self.total_received),
                "total_paid_out_wei": int(self.total_paid_out),
                "locked_wei": int(self.locked_wei),
                "credits_total_wei": int(self.credits_total),
                "contract_balance_wei": int(self.balance),
                "accounted_wei": int(self.total_paid_out + self.locked_wei + self.credits_total),
            }
        )

    @gl.public.view
    def list_bounties(self, offset: u256, limit: u256) -> str:
        if limit < 1 or limit > 20:
            raise gl.vm.UserError("EXPECTED: limit_must_be_1_to_20")
        total = int(self.next_bounty_id)
        start = int(offset)
        if start >= total:
            return json.dumps([])
        end = start + int(limit)
        if end > total:
            end = total
        out = []
        index = start
        while index < end:
            out.append(self._load_bounty(u256(index)))
            index += 1
        return json.dumps(out)

    @gl.public.view
    def list_attempts(self, offset: u256, limit: u256) -> str:
        if limit < 1 or limit > 20:
            raise gl.vm.UserError("EXPECTED: limit_must_be_1_to_20")
        total = int(self.next_attempt_id)
        start = int(offset)
        if start >= total:
            return json.dumps([])
        end = start + int(limit)
        if end > total:
            end = total
        out = []
        index = start
        while index < end:
            out.append(self._load_attempt(u256(index)))
            index += 1
        return json.dumps(out)

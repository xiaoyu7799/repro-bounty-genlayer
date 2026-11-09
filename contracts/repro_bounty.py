# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""ReproBounty: a research-replication bounty primitive for GenLayer.

A poster locks a bounty (simulated mGEN ledger units) behind a
published experiment spec. A reproducer re-runs the code and submits
the run log plus the actual output text. Validator consensus decides
whether the replication genuinely reproduced the claimed result:
REPRODUCED / FAILED / INCONCLUSIVE. The bounty is released only on
REPRODUCED. A failed or inconclusive attempt leaves the bounty locked
for the next attempt.

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
  boundary: worst-case spread is 0 verdict flips, 0 mGEN difference.

Target network: Stable Studionet only (Chain ID 61999).
All bounty money is a simulated mGEN ledger inside this contract;
no real GEN moves. Amounts are positive even integers.
"""

import json

from genlayer import *

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

DEMO_CREDIT = 10000
REPUTATION_START = 100
SCORE_TOLERANCE = 10
VERDICT_BOUNDARY = 70
MARGIN = 11
ACCEPT_MIN_REPRODUCED = 81   # VERDICT_BOUNDARY + MARGIN
ACCEPT_MAX_INCONCLUSIVE = 59  # VERDICT_BOUNDARY - MARGIN - 1
MIN_LOG_LEN = 40
MAX_OUTPUT_LEN = 2000
MAX_LOG_LEN = 4000
MAX_REF_LEN = 200


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
    balances: TreeMap[str, u256]
    claimed_demo: TreeMap[str, u256]
    reputation: TreeMap[str, u256]
    next_bounty_id: u256
    next_attempt_id: u256
    attempt_ids: DynArray[u256]

    def __init__(self):
        self.next_bounty_id = u256(0)
        self.next_attempt_id = u256(0)

    # -- deterministic helpers -------------------------------------------

    def _sender(self) -> str:
        return str(gl.message.sender_address)

    def _map_int(self, mapping, key, default: int) -> int:
        if key in mapping:
            return int(mapping[key])
        return default

    def _rep(self, address: str) -> int:
        return self._map_int(self.reputation, address, REPUTATION_START)

    def _set_rep(self, address: str, value: int) -> None:
        if value < 0:
            value = 0
        self.reputation[address] = u256(value)

    def _adjust_rep(self, address: str, delta: int) -> None:
        self._set_rep(address, self._rep(address) + delta)

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
        attempt["status"] = "FINALIZED"
        attempt["verdict"] = verdict
        attempt["pending_verdict"] = None
        reproducer = attempt["reproducer"]
        if verdict == "REPRODUCED":
            escrow = int(bounty["escrow"])
            bounty["escrow"] = 0
            bounty["status"] = "CLOSED"
            bounty["winner"] = reproducer
            self.balances[reproducer] = u256(self._map_int(self.balances, reproducer, 0) + escrow)
            self._adjust_rep(reproducer, 10)
        elif verdict == "FAILED":
            self._adjust_rep(reproducer, -5)
        # INCONCLUSIVE: escrow stays locked, bounty stays OPEN, no rep change.
        if attempt["round"] == 2 and attempt["first_verdict"] is not None:
            challenger = attempt["challenger"]
            if challenger:
                if verdict == attempt["first_verdict"]:
                    self._adjust_rep(challenger, -5)
                else:
                    self._adjust_rep(challenger, 5)

    # -- writes ------------------------------------------------------------

    @gl.public.write
    def claim_demo_funds(self) -> u256:
        sender = self._sender()
        if sender in self.claimed_demo:
            raise gl.vm.UserError("EXPECTED: demo_funds_already_claimed")
        self.claimed_demo[sender] = u256(1)
        self.balances[sender] = u256(self._map_int(self.balances, sender, 0) + DEMO_CREDIT)
        return u256(int(self.balances[sender]))

    @gl.public.write
    def post_bounty(self, spec_hash: str, code_ref: str, expected_code_hash: str,
                    expected_output_hash: str, amount: u256) -> u256:
        if not _is_hex64(spec_hash):
            raise gl.vm.UserError("EXPECTED: spec_hash_must_be_64_lowercase_hex")
        if not _is_hex64(expected_code_hash):
            raise gl.vm.UserError("EXPECTED: expected_code_hash_must_be_64_lowercase_hex")
        if not _is_hex64(expected_output_hash):
            raise gl.vm.UserError("EXPECTED: expected_output_hash_must_be_64_lowercase_hex")
        if not isinstance(code_ref, str) or len(code_ref) < 1 or len(code_ref) > MAX_REF_LEN:
            raise gl.vm.UserError("EXPECTED: code_ref_must_be_1_to_200_chars")
        amount_int = int(amount)
        if amount_int <= 0 or amount_int % 2 != 0:
            raise gl.vm.UserError("EXPECTED: amount_must_be_positive_even_integer")
        sender = self._sender()
        balance = self._map_int(self.balances, sender, 0)
        if amount_int > balance:
            raise gl.vm.UserError("EXPECTED: insufficient_simulated_balance")
        self.balances[sender] = u256(balance - amount_int)
        bounty_id = self.next_bounty_id
        self.next_bounty_id = bounty_id + u256(1)
        bounty = {
            "id": int(bounty_id),
            "poster": sender,
            "spec_hash": spec_hash,
            "code_ref": code_ref,
            "expected_code_hash": expected_code_hash,
            "expected_output_hash": expected_output_hash,
            "amount": amount_int,
            "escrow": amount_int,
            "status": "OPEN",
            "winner": None,
        }
        self._save_bounty(bounty)
        return bounty_id

    @gl.public.write
    def submit_replication(self, bounty_id: u256, code_hash: str,
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
        self._save_attempt(attempt)
        return attempt_id

    @gl.public.write
    def evaluate_replication(self, attempt_id: u256) -> str:
        attempt = self._load_attempt(attempt_id)
        bounty = self._load_bounty(u256(attempt["bounty_id"]))
        if bounty["status"] != "OPEN":
            raise gl.vm.UserError("EXPECTED: bounty_not_open")
        if attempt["status"] == "FINALIZED":
            raise gl.vm.UserError("EXPECTED: attempt_already_finalized")
        if attempt["status"] == "SUBMITTED":
            round_no = 1
        elif attempt["status"] == "EVALUATING" and attempt["challenged"] and attempt["round"] == 1:
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
            attempt["status"] = "EVALUATING"
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
    def challenge_replication(self, attempt_id: u256) -> str:
        attempt = self._load_attempt(attempt_id)
        if attempt["status"] != "EVALUATING" or attempt["round"] != 1 or attempt["challenged"]:
            raise gl.vm.UserError("EXPECTED: attempt_not_open_to_challenge")
        sender = self._sender()
        if sender == attempt["reproducer"]:
            raise gl.vm.UserError("EXPECTED: reproducer_cannot_challenge_own_attempt")
        attempt["challenged"] = True
        attempt["challenger"] = sender
        self._save_attempt(attempt)
        return json.dumps({"attempt_id": int(attempt_id), "challenger": sender, "status": "EVALUATING"})

    @gl.public.write
    def finalize_replication(self, attempt_id: u256) -> str:
        attempt = self._load_attempt(attempt_id)
        bounty = self._load_bounty(u256(attempt["bounty_id"]))
        if attempt["status"] != "EVALUATING" or attempt["round"] != 1:
            raise gl.vm.UserError("EXPECTED: attempt_not_awaiting_finalize")
        if attempt["challenged"]:
            raise gl.vm.UserError("EXPECTED: challenged_attempt_must_be_reevaluated")
        if attempt["pending_verdict"] is None:
            raise gl.vm.UserError("EXPECTED: no_pending_verdict")
        verdict = attempt["pending_verdict"]
        self._apply_final_verdict(bounty, attempt, verdict)
        self._save_bounty(bounty)
        self._save_attempt(attempt)
        return json.dumps({"attempt_id": int(attempt_id), "verdict": verdict, "status": "FINALIZED"})

    @gl.public.write
    def cancel_bounty(self, bounty_id: u256) -> str:
        bounty = self._load_bounty(bounty_id)
        if bounty["status"] != "OPEN":
            raise gl.vm.UserError("EXPECTED: bounty_not_open")
        if self._sender() != bounty["poster"]:
            raise gl.vm.UserError("EXPECTED: only_poster_can_cancel")
        for attempt_id in self.attempt_ids:
            attempt = json.loads(self.attempts[attempt_id])
            if int(attempt["bounty_id"]) == int(bounty_id) and attempt["status"] == "EVALUATING":
                raise gl.vm.UserError("EXPECTED: attempt_under_evaluation")
        escrow = int(bounty["escrow"])
        poster = bounty["poster"]
        bounty["escrow"] = 0
        bounty["status"] = "CANCELLED"
        self.balances[poster] = u256(self._map_int(self.balances, poster, 0) + escrow)
        self._save_bounty(bounty)
        return json.dumps({"bounty_id": int(bounty_id), "status": "CANCELLED", "refunded": escrow})

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
    def get_balance(self, address: str) -> u256:
        return u256(self._map_int(self.balances, address, 0))

    @gl.public.view
    def get_reputation(self, address: str) -> u256:
        return u256(self._rep(address))

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

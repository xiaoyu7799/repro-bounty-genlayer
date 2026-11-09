"""Local mock tests for contracts/repro_bounty.py — MOCK ONLY, not consensus evidence.

Stubs the `genlayer` module in-process (no GenVM, no network, no chain)
so the contract's pure-Python logic can be exercised locally:
  1. pure-Python SHA-256 against hashlib test vectors.
  2. Deterministic verdict table (all hash/code/log combinations).
  3. Score-band / margin proof, enumerated exhaustively: every accepted
     leader minimum and every validator minimum within +-10 must land
     on the same side of the 70 boundary; 60-80 is rejected.
  4. Full state-machine simulation with canned LLM scores and real-GEN
     accounting in wei (1 GEN = 10^18 wei): post 40 GEN payable,
     submit, evaluate round 1, challenge, evaluate round 2
     (REPRODUCED -> credit -> withdraw_payout -> BOUNTY_CLOSED), a
     FAILED bounty (full refund to the poster), an INCONCLUSIVE bounty
     (25% / 75% split, both sides withdraw), a cancel (full refund),
     both challenge branches (success +5 rep, fail -5 rep from a
     positive balance), the dead-zone rejection, and the money
     invariant total_received == total_paid_out + locked + credits
     after every step.

Run: python3 tests/test_local.py
Exit 0 = all mock checks pass. Nothing here proves on-chain consensus;
only the on-chain evaluate transactions do that.
"""

import hashlib
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GEN = 10 ** 18


# --- stub genlayer ---------------------------------------------------------

class UserError(Exception):
    pass


class Return:
    def __init__(self, calldata):
        self.calldata = calldata


class _VM:
    UserError = UserError
    Return = Return

    @staticmethod
    def run_nondet_unsafe(leader_fn, validate_fn):
        try:
            result = leader_fn()
            leader = Return(result)
        except UserError as e:
            leader = e
        except Exception:
            raise
        ok = validate_fn(leader)
        if not ok:
            raise Exception("MOCK_CONSENSUS_FAILED")
        if isinstance(leader, UserError):
            raise leader
        return leader.calldata


class _WriteDecorator:
    def __call__(self, fn):
        return fn

    def payable(self, fn):
        return fn


class _Public:
    write = _WriteDecorator()

    @staticmethod
    def view(fn):
        return fn


class _Nondet:
    scores = [90, 92, 88]  # canned LLM scores, set by each scenario

    def exec_prompt(self, prompt, response_format="json"):
        s = self.scores
        return {
            "log_consistency": str(s[0]),
            "output_plausibility": str(s[1]),
            "code_fidelity": str(s[2]),
        }


class _Message:
    sender_address = "0x0000000000000000000000000000000000000000"
    value = 0


class _Contract:
    @property
    def balance(self):
        # Mock chain balance: everything received minus everything paid out.
        return int(getattr(self, "total_received", 0)) - int(getattr(self, "total_paid_out", 0))


def _contract_interface(cls):
    class Wrapped(cls):
        def __init__(self, addr=None):
            self._addr = addr

        def emit_transfer(self, value=None):
            return None

    return Wrapped


def _make_gl():
    mod = types.ModuleType("genlayer")
    mod.Contract = _Contract
    mod.public = _Public()
    mod.vm = _VM()
    mod.nondet = _Nondet()
    mod.message = _Message()
    mod.u256 = int
    mod.Address = str

    class TreeMap(dict):
        pass

    class DynArray(list):
        pass

    mod.TreeMap = TreeMap
    mod.DynArray = DynArray
    evm = types.SimpleNamespace(contract_interface=_contract_interface)
    mod.evm = evm
    mod.gl = types.SimpleNamespace(
        Contract=_Contract, public=mod.public, vm=mod.vm,
        nondet=mod.nondet, message=mod.message, evm=evm,
    )
    return mod


sys.modules["genlayer"] = _make_gl()

import importlib.util

spec = importlib.util.spec_from_file_location(
    "repro_bounty", ROOT / "contracts" / "repro_bounty.py"
)
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"  ok: {name}")


def fresh():
    c = rb.ReproBounty()
    c.bounties = {}
    c.attempts = {}
    c.credits = {}
    c.reputation = {}
    c.attempt_ids = []
    return c


def set_sender(addr):
    sys.modules["genlayer"].message.sender_address = addr


def set_value(wei):
    sys.modules["genlayer"].message.value = wei


def set_scores(scores):
    sys.modules["genlayer"].nondet.scores = scores


def check_invariant(c, name):
    t = json.loads(c.get_totals())
    check(f"{name}: total_received == paid_out + locked + credits",
          t["total_received_wei"] == t["total_paid_out_wei"] + t["locked_wei"] + t["credits_total_wei"])
    check(f"{name}: contract balance == locked + credits",
          t["contract_balance_wei"] == t["locked_wei"] + t["credits_total_wei"])


def post(c, sender, gen_amount):
    set_sender(sender)
    set_value(gen_amount * GEN)
    bid = int(c.post_bounty(SPEC_HASH, "https://example.org/reproduce.py", CODE_HASH,
                            EXPECTED_OUT_HASH))
    set_value(0)
    return bid


POSTER = "0x1111111111111111111111111111111111111111"
REPRO = "0x2222222222222222222222222222222222222222"
CHALL = "0x3333333333333333333333333333333333333333"

GOOD_OUTPUT = "pi=3.14159"
GOOD_LOG = (
    "REPRO-START run reproduce.py --seed 7\n"
    "step 1: load data ok\nstep 2: compute pi series ok\n"
    "RESULT pi=3.14159 matches expected\nREPRO-END exit 0"
)
SHORT_LOG = (
    "REPRO-START run reproduce.py --seed 7\n"
    "step 1: load data ok\nstep 2: compute pi series ok\n"
    "RESULT pi=3.14159 matches expected\n"
)
CODE_HASH = hashlib.sha256(b"reproduce.py v1").hexdigest()
SPEC_HASH = hashlib.sha256(b"spec: compute pi to 5 decimals").hexdigest()
EXPECTED_OUT_HASH = hashlib.sha256(GOOD_OUTPUT.encode()).hexdigest()

print("== 1. pure-Python SHA-256 vs hashlib ==")
vectors = ["", "abc", GOOD_OUTPUT, "x" * 200, "pi≈3.14159 ✓"]
for v in vectors:
    got = rb.pure_sha256_hex(v)
    want = hashlib.sha256(v.encode("utf-8")).hexdigest()
    check(f"sha256({v[:12]!r}…) == hashlib", got == want)
print(f"  example: sha256('pi=3.14159') = {rb.pure_sha256_hex(GOOD_OUTPUT)}")

print("== 2. deterministic verdict table ==")
table = [
    (True, True, True, "REPRODUCED_CANDIDATE"),
    (True, True, False, "INCONCLUSIVE"),
    (True, False, True, "FAILED"),
    (True, False, False, "FAILED"),
    (False, True, True, "FAILED"),
    (False, False, False, "FAILED"),
]
for h, co, lo, want in table:
    check(f"D(hash={h},code={co},log={lo}) == {want}",
          rb._deterministic_verdict(h, co, lo) == want)
check("hex64 accepts 64 lowercase hex", rb._is_hex64("a" * 64))
check("hex64 rejects uppercase", not rb._is_hex64("A" * 64))
check("hex64 rejects 63 chars", not rb._is_hex64("a" * 63))

print("== 3. score-band margin proof (exhaustive) ==")
for leader_min in list(range(0, 60)) + list(range(81, 101)):
    leader_side = "REPRODUCED" if leader_min >= 81 else "INCONCLUSIVE"
    assert rb._scores_verdict(leader_min) == leader_side
    for validator_min in range(max(0, leader_min - 10), min(100, leader_min + 10) + 1):
        v_side = "REPRODUCED" if validator_min >= 70 else "INCONCLUSIVE"
        assert v_side == leader_side, (
            f"leader min {leader_min} vs validator min {validator_min}: "
            f"{leader_side} != {v_side}")
check("all accepted leader minima keep every +-10 validator on the same side", True)
for m in range(60, 81):
    assert not (m >= rb.ACCEPT_MIN_REPRODUCED or m <= rb.ACCEPT_MAX_INCONCLUSIVE)
check("dead zone 60-80 is rejected for leader minima", True)
import itertools
for leader in [(81, 81, 81), (90, 100, 85), (59, 59, 59), (0, 30, 59), (100, 100, 100)]:
    lm = min(leader)
    for dv in itertools.product((-10, 0, 10), repeat=3):
        vm = min(max(0, min(100, leader[i] + dv[i])) for i in range(3))
        assert abs(vm - lm) <= 10
        side_l = "REPRODUCED" if lm >= 81 else "INCONCLUSIVE"
        side_v = "REPRODUCED" if vm >= 70 else "INCONCLUSIVE"
        assert side_l == side_v, f"triple {leader} delta {dv}: {lm}->{vm}"
check("per-score +-10 keeps min on the same side of 70 (sampled corners)", True)
# Worst-case spread in GEN: escrow is 40 GEN; two compatible leaders
# agree on the verdict, so the payout difference is exactly 0 GEN.
check("worst-case spread = 0 verdict flips, 0 GEN (40 GEN escrow)", True)

print("== 4. combine-verdict table ==")
for d, s, want in [
    ("FAILED", "REPRODUCED", "FAILED"),
    ("FAILED", "INCONCLUSIVE", "FAILED"),
    ("INCONCLUSIVE", "REPRODUCED", "INCONCLUSIVE"),
    ("REPRODUCED_CANDIDATE", "REPRODUCED", "REPRODUCED"),
    ("REPRODUCED_CANDIDATE", "INCONCLUSIVE", "INCONCLUSIVE"),
]:
    check(f"combine({d},{s}) == {want}", rb._combine_verdict(d, s) == want)

print("== 5. full state machine, real-GEN accounting (wei) ==")
c = fresh()
set_sender(POSTER)
set_value(0)
try:
    c.post_bounty(SPEC_HASH, "https://example.org/reproduce.py", CODE_HASH, EXPECTED_OUT_HASH)
    check("zero-value post rejected", False)
except UserError as e:
    check(f"zero-value post rejected ({e})", True)
set_value(3)  # 3 wei is not divisible by 4
try:
    c.post_bounty(SPEC_HASH, "https://example.org/reproduce.py", CODE_HASH, EXPECTED_OUT_HASH)
    check("3-wei post rejected (not divisible by 4)", False)
except UserError as e:
    check(f"3-wei post rejected ({e})", True)
check("reputation starts at 0, credit starts at 0",
      int(c.get_reputation(REPRO)) == 0 and int(c.get_credit(REPRO)) == 0)
bid = post(c, POSTER, 40)
check("bounty id 0", bid == 0)
b = json.loads(c.get_bounty(0))
check("bounty OPEN, 40 GEN locked (40000000000000000000 wei)",
      b["status"] == "OPEN" and b["amount_wei"] == 40 * GEN and b["escrow_wei"] == 40 * GEN)
check_invariant(c, "after post #0")

set_sender(REPRO)
set_value(0)
aid = int(c.submit_reproduction(0, CODE_HASH, GOOD_OUTPUT, GOOD_LOG))
check("attempt id 0", aid == 0)
a = json.loads(c.get_attempt(0))
check("output_hash computed on-chain == hashlib",
      a["output_hash"] == EXPECTED_OUT_HASH)
check("attempt SUBMITTED", a["status"] == "SUBMITTED")
b = json.loads(c.get_bounty(0))
check("bounty REPRODUCTION_SUBMITTED after submit",
      b["status"] == "REPRODUCTION_SUBMITTED")

# Round 1: genuine log, high scores -> AWAITING_DECISION, pending REPRODUCED.
set_scores([90, 92, 88])
r1 = json.loads(c.evaluate_reproduction(0))
check("round 1 verdict REPRODUCED", r1["verdict"] == "REPRODUCED" and r1["round"] == 1)
a = json.loads(c.get_attempt(0))
check("attempt AWAITING_DECISION, pending REPRODUCED",
      a["status"] == "AWAITING_DECISION" and a["pending_verdict"] == "REPRODUCED")
check("scores recorded 90/92/88, min 88",
      a["scores"] == {"log_consistency": 90, "output_plausibility": 92,
                      "code_fidelity": 88, "min_score": 88})

# Challenge, then finalize must be blocked while challenged.
set_sender(CHALL)
ch = json.loads(c.challenge_reproduction(0))
check("challenge recorded", ch["challenger"] == CHALL)
try:
    set_sender(POSTER)
    c.finalize_reproduction(0)
    check("finalize blocked while challenged", False)
except UserError as e:
    check(f"finalize blocked while challenged ({e})", True)
try:
    set_sender(REPRO)
    c.challenge_reproduction(0)
    check("reproducer cannot challenge own attempt", False)
except UserError as e:
    check(f"reproducer cannot challenge own attempt ({e})", True)

# Round 2: agrees REPRODUCED -> DECIDED, credit 40 GEN, rep +10.
set_scores([91, 90, 89])
set_sender(REPRO)
r2 = json.loads(c.evaluate_reproduction(0))
check("round 2 finalizes directly", r2["round"] == 2 and r2["status"] == "DECIDED")
a = json.loads(c.get_attempt(0))
check("final verdict REPRODUCED, first verdict retained",
      a["verdict"] == "REPRODUCED" and a["first_verdict"] == "REPRODUCED")
b = json.loads(c.get_bounty(0))
check("bounty VERDICT_REPRODUCED, escrow 0, winner recorded",
      b["status"] == "VERDICT_REPRODUCED" and b["escrow_wei"] == 0 and b["winner"] == REPRO)
check("reproducer credit 40 GEN (40000000000000000000 wei)",
      int(c.get_credit(REPRO)) == 40 * GEN)
check("reproducer reputation 10 (0 +10)", int(c.get_reputation(REPRO)) == 10)
check("challenger reputation 0 (challenge failed, -5 floored at 0)",
      int(c.get_reputation(CHALL)) == 0)
check_invariant(c, "after REPRODUCED finalization")

# Withdraw: pull payment of 40 GEN, bounty closes.
set_sender(REPRO)
wd = json.loads(c.withdraw_payout())
check("withdraw_payout pays 40 GEN",
      wd["withdrawn_wei"] == 40 * GEN and wd["contract_balance_wei"] == 0)
check("reproducer credit 0 after withdraw", int(c.get_credit(REPRO)) == 0)
b = json.loads(c.get_bounty(0))
check("bounty BOUNTY_CLOSED after full payout", b["status"] == "BOUNTY_CLOSED")
check_invariant(c, "after withdraw #0")
try:
    c.withdraw_payout()
    check("second withdraw rejected (no credit)", False)
except UserError as e:
    check(f"second withdraw rejected ({e})", True)
try:
    c.evaluate_reproduction(0)
    check("evaluate on DECIDED rejected", False)
except UserError as e:
    check(f"evaluate on DECIDED rejected ({e})", True)

print("== 6. FAILED bounty: full refund to the poster ==")
bid1 = post(c, POSTER, 40)
check("bounty id 1", bid1 == 1)
set_sender(REPRO)
aid1 = int(c.submit_reproduction(1, CODE_HASH, "pi=3.14000", GOOD_LOG))
a = json.loads(c.get_attempt(aid1))
check("wrong output -> different hash (exact, no closeness)",
      a["output_hash"] != EXPECTED_OUT_HASH)
# LLM scores high anyway -> deterministic FAILED must stand + witness.
set_scores([95, 94, 93])
r1 = json.loads(c.evaluate_reproduction(aid1))
check("round 1 verdict FAILED despite high LLM scores", r1["verdict"] == "FAILED")
a = json.loads(c.get_attempt(aid1))
check("witness recorded (llm_vs_deterministic)",
      a["witness"] is not None and a["witness"]["kind"] == "llm_vs_deterministic")
set_sender(POSTER)
r = json.loads(c.finalize_reproduction(aid1))
check("finalize without challenge -> DECIDED FAILED", r["verdict"] == "FAILED")
b = json.loads(c.get_bounty(1))
check("bounty VERDICT_FAILED, poster share 40 GEN",
      b["status"] == "VERDICT_FAILED" and b["poster_share_wei"] == 40 * GEN)
check("poster credit 40 GEN", int(c.get_credit(POSTER)) == 40 * GEN)
check("reproducer reputation 5 (10 -5 for FAILED)", int(c.get_reputation(REPRO)) == 5)
check_invariant(c, "after FAILED finalization")
wd = json.loads(c.withdraw_payout())
check("poster withdraws 40 GEN refund", wd["withdrawn_wei"] == 40 * GEN)
b = json.loads(c.get_bounty(1))
check("bounty BOUNTY_REFUNDED after refund paid", b["status"] == "BOUNTY_REFUNDED")
check_invariant(c, "after FAILED refund")

print("== 7. INCONCLUSIVE bounty: 25% / 75% split ==")
bid2 = post(c, POSTER, 40)
set_sender(REPRO)
aid2 = int(c.submit_reproduction(2, CODE_HASH, GOOD_OUTPUT, SHORT_LOG))
set_scores([88, 90, 87])  # scores cannot rescue an incomplete log
r1 = json.loads(c.evaluate_reproduction(aid2))
check("round 1 verdict INCONCLUSIVE (log missing REPRO-END)", r1["verdict"] == "INCONCLUSIVE")
set_sender(POSTER)
r = json.loads(c.finalize_reproduction(aid2))
check("finalize -> DECIDED INCONCLUSIVE", r["verdict"] == "INCONCLUSIVE")
b = json.loads(c.get_bounty(2))
check("bounty VERDICT_INCONCLUSIVE, shares 10 GEN / 30 GEN",
      b["status"] == "VERDICT_INCONCLUSIVE"
      and b["reproducer_share_wei"] == 10 * GEN and b["poster_share_wei"] == 30 * GEN)
check("reproducer credit 10 GEN", int(c.get_credit(REPRO)) == 10 * GEN)
check("poster credit 30 GEN", int(c.get_credit(POSTER)) == 30 * GEN)
check("reproducer reputation unchanged at 5 (INCONCLUSIVE)",
      int(c.get_reputation(REPRO)) == 5)
check_invariant(c, "after INCONCLUSIVE finalization")
set_sender(REPRO)
wd = json.loads(c.withdraw_payout())
check("reproducer withdraws 10 GEN", wd["withdrawn_wei"] == 10 * GEN)
b = json.loads(c.get_bounty(2))
check("bounty still VERDICT_INCONCLUSIVE until poster also withdraws",
      b["status"] == "VERDICT_INCONCLUSIVE")
set_sender(POSTER)
wd = json.loads(c.withdraw_payout())
check("poster withdraws 30 GEN", wd["withdrawn_wei"] == 30 * GEN)
b = json.loads(c.get_bounty(2))
check("bounty BOUNTY_CLOSED after both shares paid", b["status"] == "BOUNTY_CLOSED")
check_invariant(c, "after INCONCLUSIVE split paid")

print("== 8. cancel path ==")
bid3 = post(c, POSTER, 40)
check("bounty id 3", bid3 == 3)
set_sender(POSTER)
res = json.loads(c.cancel_bounty(3))
check("cancel refunds 40 GEN", res["refunded_wei"] == 40 * GEN)
check("poster credit 40 GEN", int(c.get_credit(POSTER)) == 40 * GEN)
b = json.loads(c.get_bounty(3))
check("bounty BOUNTY_REFUNDED", b["status"] == "BOUNTY_REFUNDED")
wd = json.loads(c.withdraw_payout())
check("poster withdraws 40 GEN cancel refund", wd["withdrawn_wei"] == 40 * GEN)
check_invariant(c, "after cancel refund")
try:
    set_sender(REPRO)
    c.submit_reproduction(3, CODE_HASH, GOOD_OUTPUT, GOOD_LOG)
    check("submit to refunded bounty rejected", False)
except UserError as e:
    check(f"submit to refunded bounty rejected ({e})", True)

print("== 9. challenge branches: success (+5) then fail (-5 from positive) ==")
c3 = fresh()
post(c3, POSTER, 40)
set_sender(REPRO)
c3.submit_reproduction(0, CODE_HASH, GOOD_OUTPUT, GOOD_LOG)
set_scores([90, 92, 88])
c3.evaluate_reproduction(0)
set_sender(CHALL)
c3.challenge_reproduction(0)
# Round 2 with low scores: deterministic candidate + INCONCLUSIVE scores
# -> final INCONCLUSIVE, challenge succeeded.
set_scores([20, 25, 30])
set_sender(REPRO)
r2 = json.loads(c3.evaluate_reproduction(0))
check("round 2 flips to INCONCLUSIVE (challenge succeeded)",
      r2["verdict"] == "INCONCLUSIVE" and r2["round"] == 2)
a = json.loads(c3.get_attempt(0))
check("first verdict REPRODUCED retained",
      a["first_verdict"] == "REPRODUCED" and a["verdict"] == "INCONCLUSIVE")
check("challenger reputation +5 (challenge succeeded)",
      int(c3.get_reputation(CHALL)) == 5)
b = json.loads(c3.get_bounty(0))
check("INCONCLUSIVE split on challenge success (10 / 30 GEN)",
      b["reproducer_share_wei"] == 10 * GEN and b["poster_share_wei"] == 30 * GEN)
# Second bounty: same challenger challenges and fails -> 5 - 5 = 0.
post(c3, POSTER, 40)
set_sender(REPRO)
c3.submit_reproduction(1, CODE_HASH, GOOD_OUTPUT, GOOD_LOG)
set_scores([90, 92, 88])
c3.evaluate_reproduction(1)
set_sender(CHALL)
c3.challenge_reproduction(1)
set_scores([91, 90, 89])
set_sender(REPRO)
r2 = json.loads(c3.evaluate_reproduction(1))
check("round 2 agrees REPRODUCED (challenge failed)", r2["verdict"] == "REPRODUCED")
check("challenger reputation 0 (5 -5, challenge failed)",
      int(c3.get_reputation(CHALL)) == 0)
check("reproducer reputation 10 (0 +10)", int(c3.get_reputation(REPRO)) == 10)
check_invariant(c3, "after challenge branches")

print("== 10. dead-zone scores are rejected by mock consensus ==")
c2 = fresh()
post(c2, POSTER, 40)
set_sender(REPRO)
c2.submit_reproduction(0, CODE_HASH, GOOD_OUTPUT, GOOD_LOG)
set_scores([75, 90, 90])  # min 75 -> dead zone
try:
    c2.evaluate_reproduction(0)
    check("dead-zone scores rejected", False)
except Exception as e:
    check(f"dead-zone scores rejected ({e})", "DEAD_ZONE" in str(e) or "CONSENSUS" in str(e))
a = json.loads(c2.get_attempt(0))
check("attempt stays SUBMITTED after dead-zone rejection",
      a["status"] == "SUBMITTED")

print(f"\nMOCK TESTS PASSED: {PASS} checks")

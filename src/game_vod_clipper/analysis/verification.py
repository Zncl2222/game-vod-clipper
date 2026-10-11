"""Spend stronger-model calls only on bounded, concrete verification questions."""
from .sampling import affects_preferred
from .validation import localized_ending, verified_entry, verified_outcome

VERIFICATION_LIMIT = 3


def verification_reason(purpose, request, previous, local, reviews):
    if len(reviews) >= VERIFICATION_LIMIT:
        return None
    used = {r["role"] for r in reviews}
    entry_context = (purpose == "entry" and "entry" not in used and request[2] <= .5
                     and request[1] - request[0] <= 20 and localized_ending(previous)
                     and previous.start is not None and request[0] <= previous.start <= request[1])
    if local is None:
        if entry_context:
            return "entry", "核對競技場進場，排除重生與跑圖"
        if (purpose == "refine" and "ending" not in used and previous
                and previous.victory is not None and request[0] <= previous.victory <= request[1]
                and not localized_ending(previous)):
            return "ending", "定位首次敗北／完成提示"
        proof = previous.ending_proof if previous else None
        if (purpose == "suspicious" and "ending" not in used and request[2] <= .5
                and request[1] - request[0] <= 20 and not localized_ending(previous)
                and proof and proof.last_combat and request[0] <= proof.last_combat.time <= request[1]):
            return "ending", "定位首次敗北／完成提示"
        return None
    if (purpose in {"refine", "outcome", "boundaries"} and "ending" not in used
            and verified_outcome(local) and local.victory is not None
            and request[0] <= local.victory <= request[1]):
        return "ending", "定位首次敗北／完成提示"
    if (entry_context or (purpose == "entry" and "entry" not in used and verified_entry(local)
            and request[0] <= local.entry_proof.time <= request[1])):
        return "entry", "核對競技場進場，排除重生與跑圖"
    if purpose in {"dense", "suspicious", "boundaries"} and "transition" not in used and request[2] <= .5:
        target = previous if localized_ending(previous) else local
        if any(w.end - w.start <= 4 and request[0] <= w.start <= w.end <= request[1]
               and affects_preferred(w.start, w.end, target) for w in local.suspicious_windows):
            return "transition", "分辨死亡重試與連續戰鬥中的轉階段"
    return None

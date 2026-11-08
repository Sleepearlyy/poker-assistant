"""Pure parsers: deliberately never turn unreadable values into zero."""
import re
from decimal import Decimal

AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[KkMm万]?"

def format_chips(value, signed=False):
    """Compact display only; amounts used by the solver retain their full precision."""
    number = Decimal(str(value))
    magnitude = abs(number)
    scale, suffix = (Decimal(1000000), 'M') if magnitude >= 1000000 else ((Decimal(1000), 'K') if magnitude >= 1000 else (Decimal(1), ''))
    rounded = (number / scale).quantize(Decimal('0.01'))
    if suffix == 'K' and abs(rounded) >= 1000:
        rounded, suffix = (number / 1000000).quantize(Decimal('0.01')), 'M'
    text = format(rounded, 'f').rstrip('0').rstrip('.') if '.' in format(rounded, 'f') else format(rounded, 'f')
    if rounded == 0:
        text = '0'
    if signed and rounded >= 0:
        text = '+' + text
    return text + suffix

def amount(text):
    value = re.sub(r"\s+", "", text).replace("，", ",")
    if not re.fullmatch(AMOUNT, value):
        return None
    suffix = value[-1].upper()
    multiplier = {"K": 1000, "M": 1000000, "万": 10000}.get(suffix, 1)
    number = value[:-1] if multiplier != 1 else value
    result = Decimal(number.replace(",", "")) * multiplier
    return {"value": int(result) if result == int(result) else float(result),
            "display": text, "approximate": multiplier != 1}

def numeric(lines, threshold=0.8):
    candidates = [(amount(x["text"]), x["score"]) for x in lines if x["score"] >= threshold]
    candidates = [(a, score) for a, score in candidates if a is not None]
    if not candidates or len({a["value"] for a, _ in candidates}) != 1:
        return None
    a, score = max(candidates, key=lambda x: x[1])
    return dict(a, confidence=round(score, 3))

def blinds(lines):
    for row in lines:
        if row["score"] < 0.8:
            continue
        match = re.search(rf"({AMOUNT})\s*[/／]\s*({AMOUNT})", row["text"])
        if match:
            small, big = amount(match[1]), amount(match[2])
            if small["value"] <= 0 or big["value"] < small["value"]:
                continue
            return {"small": small["value"], "big": big["value"],
                    "approximate": small["approximate"] or big["approximate"],
                    "confidence": round(row["score"], 3), "raw": row["text"]}
    return None

def facing_button(text):
    """跟注 disappears when the stack cannot cover the bet. Then only all-in or fold remains."""
    text = text or ""
    if re.search(r"过\s*牌|過\s*牌|\bcheck\b", text, re.I):
        return {"to_call": 0, "source": "check_button", "hero_turn": True}
    if re.search(r"跟\s*注|\bcall\b", text, re.I):
        nums = re.findall(AMOUNT, text)
        parsed = amount(nums[0]) if len(nums) == 1 else None
        return {"to_call": parsed["value"] if parsed else None,
                "source": "call_button", "hero_turn": True}
    if re.search(r"弃\s*牌|棄\s*牌|加\s*注|全\s*下|全\s*押|all[\s_-]*in|\bfold\b|\braise\b", text, re.I):
        nums = re.findall(AMOUNT, text)
        parsed = amount(nums[0]) if len(nums) == 1 else None
        return {"to_call": parsed["value"] if parsed else None,
                "source": "all_in_button", "hero_turn": True}
    return {"to_call": None, "source": None, "hero_turn": False}

def _center(row):
    box = row.get("box")
    if not box:
        return None
    return (sum(p[0] for p in box) / len(box), sum(p[1] for p in box) / len(box))

def action(lines):
    aliases = [("all_in", r"all[\s_-]*in|全下|全押"), ("fold", r"fold|弃\s*牌|棄\s*牌"),
               ("check", r"check|过\s*牌|過\s*牌"), ("call", r"call|跟\s*注"),
               ("raise", r"raise|加\s*注"), ("bet", r"\bbet\b|下\s*注"),
               ("small_blind", r"\bSB\b|小盲"), ("big_blind", r"\bBB\b|大盲")]
    good = [x for x in lines if x["score"] >= 0.75]
    text = " ".join(x["text"] for x in good)
    label = next((key for key, pattern in aliases if re.search(pattern, text, re.I)), None)
    bets = []
    for row in good:
        parsed = amount(re.sub(r"\s+", "", row["text"]))
        if parsed is None:
            found = re.findall(AMOUNT, row["text"])
            if len(found) == 1:
                parsed = amount(found[0])
        if parsed is not None:
            bets.append((parsed, row))
    bet = None
    if len(bets) == 1:
        bet = dict(bets[0][0], confidence=round(bets[0][1]["score"], 3))
    elif len(bets) > 1 and label:
        # The pot number often sits next to a blind chip. Keep the amount beside the label.
        pattern = dict(aliases)[label]
        anchors = [row for row in good if re.search(pattern, row["text"], re.I)]
        anchor = _center(anchors[0]) if anchors else None
        def distance(row):
            point = _center(row)
            if anchor is None or point is None:
                return 0
            return (point[0] - anchor[0]) ** 2 + (point[1] - anchor[1]) ** 2
        parsed, row = min(bets, key=lambda item: distance(item[1]))
        bet = dict(parsed, confidence=round(row["score"], 3))
    # This is the visible action-associated amount, NOT a reconstructed street contribution.
    return {"action": label, "displayed_bet": bet}

# I/L/| are the usual misreads of a hooked J. Other blurry ranks stay as whatever
# OCR actually returned; they are not folded into J.
_RANK_LOOKALIKE = str.maketrans({"I": "J", "L": "J", "|": "J"})

def card_rank(lines, threshold=0.35):
    ranks = []
    for row in lines:
        if row["score"] < threshold:
            continue
        value = row["text"].strip().upper().translate(_RANK_LOOKALIKE)
        value = re.sub(r"[^0-9A-Z]", "", value)
        if re.fullmatch(r"10|[2-9AJQK]", value):
            ranks.append((value, row["score"]))
    if len({r for r, _ in ranks}) != 1:
        return None
    rank, score = max(ranks, key=lambda x: x[1])
    return {"rank": rank, "confidence": round(score, 3)}

SEAT_ORDER = ["top", "upper_right", "lower_right", "bottom", "lower_left", "upper_left"]

def _roles_from_button(occupied, button):
    start = occupied.index(button)
    ring = occupied[start:] + occupied[:start]
    count = len(ring)
    if count == 1:
        names = ["按钮"]
    elif count == 2:
        names = ["按钮", "大盲"]
    else:
        between = count - 3
        if between <= 1:
            middle = ["枪口"][:max(between, 0)]
        elif between == 2:
            middle = ["枪口", "关煞"]
        elif between == 3:
            middle = ["枪口", "劫位", "关煞"]
        else:
            middle = ["枪口"] + [f"中位{i}" for i in range(1, between - 1)] + ["关煞"]
        names = ["按钮", "小盲", "大盲"] + middle
    return dict(zip(ring, names))

def assign_roles(seats, dealer_seat):
    """Name occupied seats from the button, clockwise. Skip empty chairs.

    While 小盲/大盲 are still printed on the felt, those words win over the
    dealer-button match. After the flop the words disappear and the button remains.
    """
    occupied = [seat["seat"] for seat in seats if seat.get("presence") == "occupied"]
    occupied = [seat for seat in SEAT_ORDER if seat in occupied]
    roles = {seat["seat"]: None for seat in seats}
    if not occupied:
        return roles
    sb = next((s["seat"] for s in seats if s.get("blind_role") == "small_blind" and s["seat"] in occupied), None)
    bb = next((s["seat"] for s in seats if s.get("blind_role") == "big_blind" and s["seat"] in occupied), None)
    button = dealer_seat if dealer_seat in occupied else None
    if len(occupied) == 2 and sb:
        button = sb
    elif sb and bb and len(occupied) >= 3:
        index = occupied.index(sb)
        if occupied[(index + 1) % len(occupied)] == bb:
            button = occupied[(index - 1) % len(occupied)]
    if button is None:
        if sb:
            roles[sb] = "小盲"
        if bb:
            roles[bb] = "大盲"
        return roles
    roles.update(_roles_from_button(occupied, button))
    return roles

def visible_pot(snapshot):
    """Preflop chips are still in front of players, so the center pot is often blank.

    Sum the amounts on the table only when hero's cards are known and no community
    card is showing. A half-read board is left unknown instead of called a preflop pot.
    """
    hero = snapshot.get("hero_cards") or []
    board = snapshot.get("board_cards") or []
    if not any(c.get("card") for c in hero):
        return None
    if any(c.get("card") or c.get("status") == "unreadable" for c in board):
        return None
    bets = [s["displayed_bet"]["value"] for s in snapshot.get("seats") or [] if s.get("displayed_bet")]
    if not bets:
        return None
    total = sum(bets)
    if total <= 0:
        return None
    total = int(total) if total == int(total) else total
    return {"value": total, "display": str(total), "approximate": True,
            "confidence": None, "source": "visible_bets"}

class Stability:
    """Confirm consecutive observations; never silently carry stale data forward."""
    def __init__(self, frames=2):
        self.frames = frames
        self.previous = {}

    def observe(self, key, value):
        old, count = self.previous.get(key, (None, 0))
        count = count + 1 if value is not None and old == value else (1 if value is not None else 0)
        self.previous[key] = (value, count)
        return "confirmed" if count >= self.frames else ("pending" if count else "unknown")

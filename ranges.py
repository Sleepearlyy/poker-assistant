"""Opponent ranges as explicit combo lists, narrowed by hand strength.

Preflop strength: 169 hand classes ordered by (heads-up/2 + 3-way) equity
against random hands. Postflop strength: made hand on the current board;
flush draws and open-ended straight draws rank with the weakest pair.
"""
import math
from collections import Counter

RANKS = '23456789TJQKA'
SUITS = 'cdhs'
PREFLOP_ORDER = (
    'AA KK QQ JJ TT 99 AKs 88 AQs AKo AJs 77 ATs KQs AQo KJs AJo A9s KTs ATo KQo 66 QJs A8s '
    'KJo A7s K9s QTs A5s A9o KTo A6s JTs QJo A4s 55 A8o Q9s K8s A3s QTo A7o K9o K7s J9s A2s '
    'K6s A5o JTo A6o T9s Q8s A4o K5s 44 Q9o J8s K8o K4s A3o K7o J9o Q7s K3s A2o T8s Q6s K6o '
    'K2s T9o J7s 98s Q8o Q5s K5o J8o 33 T7s K4o Q4s J6s 97s Q3s Q7o J5s T8o K3o Q6o Q2s 98o '
    'J4s T6s 87s K2o J7o Q5o 96s 22 J3s 86s Q4o T7o J2s 76s J6o T5s 97o T4s 95s Q3o J5o 87o '
    'Q2o 85s T6o T3s J4o 75s 65s 96o T2s 94s J3o 86o 54s 84s 64s 93s 74s 76o J2o T5o 92s T4o '
    '95o 85o 53s T3o 83s 75o 65o 73s 63s 82s 43s T2o 94o 54o 93o 52s 84o 64o 74o 62s 72s 42s '
    '92o 32s 53o 83o 73o 82o 63o 43o 52o 72o 42o 62o 32o').split()
CLASS_RANK = {name: i for i, name in enumerate(PREFLOP_ORDER)}


def hand_class(a, b):
    if RANKS.index(a[0]) < RANKS.index(b[0]):
        a, b = b, a
    if a[0] == b[0]:
        return a[0] + b[0]
    return a[0] + b[0] + ('s' if a[1] == b[1] else 'o')


def text(a, b):
    """The solver's parser wants the higher rank first: QsJd, not JdQs."""
    return a + b if RANKS.index(a[0]) >= RANKS.index(b[0]) else b + a


DECK = [r + s for r in RANKS for s in SUITS]
ALL_COMBOS = sorted(((a, b) for i, a in enumerate(DECK) for b in DECK[i + 1:]),
                    key=lambda c: CLASS_RANK[hand_class(*c)])


def preflop_top(fraction, dead=()):
    """Best `fraction` of all live combos by preflop strength."""
    dead = set(dead)
    live = [c for c in ALL_COMBOS if c[0] not in dead and c[1] not in dead]
    return live[:max(1, math.ceil(len(live) * fraction))]


def _straight(ranks):
    ranks = set(ranks)
    if 14 in ranks:
        ranks.add(1)
    for top in range(14, 4, -1):
        if all(r in ranks for r in range(top - 4, top + 1)):
            return top
    return 0


def strength(cards):
    ranks = [RANKS.index(c[0]) + 2 for c in cards]
    counts = Counter(ranks)
    suited = {}
    for r, c in zip(ranks, cards):
        suited.setdefault(c[1], set()).add(r)
    flush = next((v for v in suited.values() if len(v) >= 5), None)
    if flush and _straight(flush):
        return (8, _straight(flush))
    order = sorted(counts, key=lambda r: (counts[r], r), reverse=True)
    distinct = sorted(counts, reverse=True)
    if counts[order[0]] == 4:
        return (7, order[0], max(r for r in distinct if r != order[0]))
    trips = [r for r in order if counts[r] == 3]
    pairs = [r for r in order if counts[r] >= 2]
    if trips and len(pairs) >= 2:
        return (6, trips[0], next(r for r in pairs if r != trips[0]))
    if flush:
        return (5,) + tuple(sorted(flush, reverse=True)[:5])
    high = _straight(ranks)
    if high:
        return (4, high)
    if trips:
        return (3, trips[0]) + tuple(r for r in distinct if r != trips[0])[:2]
    if len(pairs) >= 2:
        return (2, pairs[0], pairs[1], max(r for r in distinct if r not in pairs[:2]))
    if pairs:
        return (1, pairs[0]) + tuple(r for r in distinct if r != pairs[0])[:3]
    return (0,) + tuple(distinct[:5])


def _draw(hole, board):
    cards = list(hole) + list(board)
    suits = Counter(c[1] for c in cards)
    if any(n == 4 and any(h[1] == s for h in hole) for s, n in suits.items()):
        return True
    ranks = {RANKS.index(c[0]) + 2 for c in cards}
    hole_ranks = {RANKS.index(c[0]) + 2 for c in hole}
    for low in range(2, 11):
        window = set(range(low, low + 4))
        if window <= ranks and window & hole_ranks and low + 3 < 14:
            return True
    return False


def board_key(hole, board):
    made = strength(list(hole) + list(board))
    if made[0] == 0 and len(board) < 5 and _draw(hole, board):
        return (1, 0)
    return made


def postflop_top(combos, board, fraction):
    ranked = sorted(combos, key=lambda c: board_key(c, board), reverse=True)
    return ranked[:max(1, math.ceil(len(ranked) * fraction))]


def range_text(combos):
    return ','.join(text(a, b) for a, b in combos)

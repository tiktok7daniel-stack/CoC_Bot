"""
The bot's own match memory: it learns from every battle it plays, on top of the 252k pro games.

  during the battle  every defense is remembered (their card, our card, the lane, our tower's health then);
                     8 s later it is judged: did our tower on that lane keep its health? -> worked / failed
  every decision     the answers that worked against that card before score higher, the failed ones lower
  after the battle   what they played, on which lane, their deck type, what worked -> a short summary (log + phone)
Stored per account: ~/.CoC_Bot/learn/royale_memory_<account>.json
"""
import json, os, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "learn"
JUDGE_S = 8.0


def _path(acc):
    return DIR / f"royale_memory_{''.join(c for c in str(acc) if c.isalnum() or c in '-_') or 'main'}.json"


class Memory:
    def __init__(self, acc):
        self.acc = acc
        try:
            self.d = json.loads(_path(acc).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.d = {}
        self.d.setdefault("answers", {})       # "threat|our card" -> {"ok": n, "bad": n}
        self.d.setdefault("opponents", {})     # their card -> times seen (what this account meets)
        self.d.setdefault("battles", [])
        self.pending = []
        self.log = []                          # this battle's defenses with their verdicts

    # -------------------------------------------------------------- in the battle
    def start(self):
        self.pending, self.log = [], []

    @staticmethod
    def _hp(towers, side):
        v = (towers or {}).get(f"our_{side}")
        try: return float(v)
        except (TypeError, ValueError): return None

    def defended(self, threat, mine, side, towers, now, predicted=None, tile=None):
        if not threat or not mine: return
        self.pending.append({"threat": threat, "mine": mine, "side": side, "t": now, "hp": self._hp(towers, side),
                             "pred": predicted, "tile": list(tile) if tile else None})

    # -------------------------------------------------------------- where it worked (6.9.18: the replay heat maps)
    # Every answer is remembered WITH ITS TILE: our own defences, and the OPPONENTS' defences against our attacks (the
    # board turned round to our side) — a heat map per (their threat, our card) of the tiles that held. Tiles are kept
    # for the left lane (a right-lane tile is mirrored), so both lanes teach each other.
    @staticmethod
    def _norm(x, y):
        x = float(x)
        return (int(round(17 - x)) if x > 8.5 else int(round(x)), int(round(y)))

    @staticmethod
    def _denorm(x, y, side):
        return (17 - x if side == "right" else x, y)

    def _heat_add(self, threat, mine, tile, ok):
        if not tile: return
        nx, ny = self._norm(*tile)
        h = self.d.setdefault("heat", {}).setdefault(f"{threat}|{mine}", {})
        c = h.setdefault(f"{nx},{ny}", [0, 0])
        c[0 if ok else 1] += 1

    def opp_defended(self, our_card, their_card, side, tile_theirs, towers, now):
        """They answered our `our_card` attack on `side` with `their_card` at `tile_theirs` (our board): judged like
        ours 8 s later on THEIR tower; when it held, the tile — turned round to our half — is a tile to try when we
        meet `our_card` ourselves."""
        if not our_card or not their_card or not tile_theirs: return
        x, y = tile_theirs
        self.pending.append({"opp": True, "threat": our_card, "mine": their_card, "side": side, "t": now,
                             "hp": self._hp_their(towers, side), "tile": [17 - x, 31 - y]})

    @staticmethod
    def _hp_their(towers, side):
        v = (towers or {}).get(f"their_{side}")
        try: return float(v)
        except (TypeError, ValueError): return None

    def best_tiles(self, threat, mine, side, k=3, min_n=2):
        """The tiles where `mine` held against `threat` most often (ours + theirs), for `side`: [((x, y), rate, n)]."""
        h = (self.d.get("heat") or {}).get(f"{threat}|{mine}") or {}
        out = []
        for key, (ok, bad) in h.items():
            n = ok + bad
            if n < min_n: continue
            rate = (ok + 1) / (n + 2)
            if rate < 0.55: continue
            nx, ny = (int(v) for v in key.split(","))
            out.append((self._denorm(nx, ny, side), round(rate, 2), n))
        return sorted(out, key=lambda r: (-r[1], -r[2]))[:k]

    def tick(self, towers, now):
        keep = []
        for p in self.pending:
            if now - p["t"] < JUDGE_S:
                keep.append(p); continue
            hp0 = p["hp"]
            hp1 = self._hp_their(towers, p["side"]) if p.get("opp") else self._hp(towers, p["side"])
            if hp0 is None or hp1 is None or hp0 <= 0: continue
            ok = (hp0 - hp1) / hp0 < 0.08                  # the tower lost (almost) nothing: the answer held
            self._heat_add(p["threat"], p["mine"], p.get("tile"), ok)
            if p.get("opp"):                               # their answer: only its tile is learned
                continue
            if p.get("pred") is not None:                  # the simulation's guess against what really happened
                actual = max(0.0, (hp0 - hp1) / hp0)
                c = self.d.setdefault("calib", {"ratio": 1.0, "n": 0})
                r = (actual + 0.03) / (float(p["pred"]) + 0.03)
                c["ratio"] = max(0.6, min(1.6, c["ratio"] * 0.9 + r * 0.1))
                c["n"] += 1
            st = self.d["answers"].setdefault(f"{p['threat']}|{p['mine']}", {"ok": 0, "bad": 0})
            st["ok" if ok else "bad"] += 1
            self.log.append((p["threat"], p["mine"], ok))
        self.pending = keep

    def calib(self):
        """How much harder (>1) or softer (<1) their attacks really hit than the simulation thought (after 10+)."""
        c = self.d.get("calib") or {}
        return c.get("ratio", 1.0) if c.get("n", 0) >= 10 else 1.0

    def bonus(self, threat, mine):
        """How our own battles rate `mine` against `threat` (nothing until tried twice): -1.5 .. +1.5, and a
        mistake made 3+ times that almost never works (< 30%) is not made again (-4)."""
        st = self.d["answers"].get(f"{threat}|{mine}")
        if not st or st["ok"] + st["bad"] < 2: return 0.0
        rate = (st["ok"] + 1) / (st["ok"] + st["bad"] + 2)
        if st["bad"] >= 3 and st["ok"] / (st["ok"] + st["bad"]) < 0.3: return -4.0
        return 3.0 * (rate - 0.5)

    # -------------------------------------------------------------- after the battle
    def end(self, won, enemy_plays, arch):
        """enemy_plays: [(seconds, card, lane)] -> the summary (Egyptian Arabic) and saved."""
        cards = {}
        lanes = {"left": 0, "right": 0}
        for _t, c, ln in enemy_plays:
            cards[c] = cards.get(c, 0) + 1
            lanes[ln] = lanes.get(ln, 0) + 1
            self.d["opponents"][c] = self.d["opponents"].get(c, 0) + 1
        good = sorted({f"{m} ضد {t}" for t, m, ok in self.log if ok})
        bad = sorted({f"{m} ضد {t}" for t, m, ok in self.log if not ok})
        self.d["battles"].append({"t": round(time.time()), "won": won, "their": cards, "lanes": lanes, "arch": arch,
                                  "good": good, "bad": bad})
        self.d["battles"] = self.d["battles"][-300:]
        try:
            DIR.mkdir(parents=True, exist_ok=True)
            p = _path(self.acc)
            tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(self.d, ensure_ascii=False, default=str), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass
        main_lane = "الشمال" if lanes["left"] >= lanes["right"] else "اليمين"
        lines = [f"🧠 اتعلمت من الماتش ({'فوز' if won else 'خسارة' if won is not None else '؟'}):",
                 f"لعب ضدي: {', '.join(sorted(cards, key=lambda c: -cards[c])) or '—'}",
                 f"نوع الديك: {arch or 'مش واضح'} — هجم أكتر من {main_lane}"]
        if good: lines.append("نفع: " + "، ".join(good[:5]))
        if bad: lines.append("ما نفعش (هقلّله): " + "، ".join(bad[:5]))
        return "\n".join(lines)

"""Per-account catalogue selection and pre-match verification."""
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from royale import cr_api, deck_catalog, deck_pick

DIR = Path.home() / ".CoC_Bot" / "catalog_decks"


def _path(account, suffix):
    from settings import _safe_id
    return DIR / f"{_safe_id(account)}.{suffix}.json"


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
        tmp = Path(file.name)
        try:
            json.dump(data, file)
            file.close()
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def selection(account):
    path = _path(account, "selection")
    try:
        picked = json.loads(path.read_text(encoding="utf-8"))
        if (isinstance(picked, dict) and isinstance(picked.get("id"), str) and picked.get("revision")
                and type(picked.get("slot")) is int and 0 <= picked["slot"] <= 10):
            return picked
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        pass
    return {"id": "invalid", "slot": 0, "revision": "invalid"}


def select(account, deck_id, slot=0):
    if type(slot) is not int or not 0 <= slot <= 10:
        return {"ok": False, "error": "invalid_slot"}
    if deck_id:
        prepared = deck_catalog.prepare_copy(deck_id)
        if not prepared["ok"]:
            return prepared
    picked = {"id": deck_id, "slot": slot, "revision": uuid4().hex}
    _write(_path(account, "selection"), picked)
    return {"ok": True, "selection": picked}


def state(account):
    picked = selection(account)
    status = _read(_path(account, "status"))
    if not picked.get("id"):
        status = {"state": "none"}
    elif picked.get("revision") != status.get("revision"):
        status = {"state": "pending"}
    deck = deck_catalog.lookup(picked["id"]) if picked.get("id") else None
    return {"selection": picked, "status": status, "deck_name": deck["name"] if deck else ""}


def report(account, picked, status, reason=""):
    _write(_path(account, "status"), {"revision": picked["revision"], "state": status, "reason": reason})


def verified(profile, deck):
    """Compare active card IDs and equipped variants when the source identifies them."""
    current = profile.get("currentDeck") or []
    if len(current) != 8 or set(c.get("id") for c in current) != set(deck["card_ids"]):
        return False
    if not deck["forms_known"]:
        return True
    return sorted(deck_catalog.api_card_variant(c) for c in current) == list(deck_catalog.signature(deck["cards"]))


def activate(account, picked, eyes, log):
    """Return verified card names or a reason. The caller keeps matchmaking blocked on failure."""
    from royale.brain import card

    prepared = deck_catalog.prepare_copy(picked["id"])
    if not prepared["ok"]:
        return [], prepared["error"]
    deck = prepared["deck"]
    names_by_id = {c.id_: name for name, c in eyes.by_name.items() if c.id_ > 0}
    names = [names_by_id.get(ident) for ident in prepared["ids"]]
    if any(not name or not card(name) for name in names):
        return [], "unsupported_cards"
    if deck_catalog.unverified_arena_cards(deck["cards"]):
        return [], "arena_vision_unverified"
    tag = cr_api.tag(account)
    if not tag:
        return [], "verification_api"
    path = f"/players/{tag}"
    try:
        profile = cr_api.fetch(path)
    except Exception:
        return [], "verification_api"
    owned = {c.get("id") for c in profile.get("cards") or []}
    if not set(prepared["ids"]).issubset(owned):
        return [], "cards_not_owned" if owned else "verification_api"
    slot = picked["slot"]
    if slot == 0 and verified(profile, deck):
        return names, ""
    # For known special forms, verify the account can equip them before replacing a slot.
    if deck["forms_known"]:
        by_id = {c.get("id"): c for c in profile.get("cards") or []}
        for expected, ident in zip(deck["cards"], prepared["ids"]):
            required = 2 if expected.endswith("-hero") else 1 if expected.endswith(("-ev1", "-ev2")) else 0
            if required and (by_id[ident].get("evolutionLevel") or 0) < required:
                return [], "forms_unavailable"
    if selection(account) != picked:
        return [], "changed"
    if not deck_pick.apply(account, {"ids": prepared["ids"]}, log, slot, strict_slot=True):
        return [], "copy_failed"
    for attempt in range(3):
        if attempt:
            from time import sleep
            sleep(1.5)
        try:
            if verified(cr_api.fetch(path), deck):
                return names, ""
        except Exception:
            return [], "verification_api"
    return [], "deck_mismatch"

"""Your home screen layout: favourite tiles and the order of tiles in a row.

Kept in settings.json with the Settings app's other choices:

- "favorites": tile ids in your order, e.g. ["kodi", "game:steam:620"].
  Any tile can be a favourite: an app, a game from the Library, a PC game.
  They make the Favorites row at the top. (Replaces "pins", game keys only,
  from before; those carry over.)
- "order": {row title: [tile ids]}: tiles you moved. Tiles not listed (new
  apps, say) keep their usual place after the ones you arranged.
"""

from __future__ import annotations

from dataclasses import replace

from . import settings

FAVORITES = "Favorites"
# Rows whose contents Hearth decides (by recency, pause time): not rearranged.
FIXED_ROWS = ("Quick Resume", "Continue")


def favorites(prefs: dict | None = None) -> list[str]:
    prefs = settings.load() if prefs is None else prefs
    if "favorites" in prefs:
        return [str(k) for k in prefs["favorites"]]
    return [f"game:{k}" for k in prefs.get("pins", [])]  # pinned games, from before


def can_favorite(tile_id: str) -> bool:
    return not tile_id.startswith("resume:")


def set_favorite(tile_id: str, on: bool) -> list[str]:
    data = settings.load()
    favs = [k for k in favorites(data) if k != tile_id]
    if on:
        favs.append(tile_id)
    data["favorites"] = favs
    data.pop("pins", None)
    settings.save(data)
    return favs


def toggle_favorite(tile_id: str) -> bool:
    """Returns True if it's now a favourite."""
    on = tile_id not in favorites()
    set_favorite(tile_id, on)
    return on


def can_move(row_title: str) -> bool:
    return row_title not in FIXED_ROWS


def save_order(row_title: str, ids: list[str]) -> None:
    data = settings.load()
    if row_title == FAVORITES:
        data["favorites"] = list(ids)
        data.pop("pins", None)
    else:
        data.setdefault("order", {})[row_title] = list(ids)
    settings.save(data)


def arrange(apps: tuple, order: list[str] | None) -> tuple:
    """`apps` in your saved order; the rest after them, as they were."""
    if not order:
        return apps
    rank = {k: i for i, k in enumerate(order)}
    placed = sorted((a for a in apps if a.id in rank), key=lambda a: rank[a.id])
    return tuple(placed) + tuple(a for a in apps if a.id not in rank)


def favorites_row(tiles: dict, favs: list[str], extra: tuple = ()):
    """The Favorites row: your favourites (those still around) in your
    order, then `extra` (ES-DE's starred games) not already there."""
    from .config import Row

    apps = [tiles[k] for k in favs if k in tiles]
    seen = {a.id for a in apps}
    apps += [a for a in extra if a.id not in seen]
    return Row(FAVORITES, tuple(apps)) if apps else None


def apply_order(config, prefs: dict | None = None):
    """Rows with your saved tile order."""
    prefs = settings.load() if prefs is None else prefs
    order = prefs.get("order") or {}
    if not isinstance(order, dict) or not order:
        return config
    rows = tuple(replace(r, apps=arrange(r.apps, order.get(r.title))) if r.title in order else r
                 for r in config.rows)
    return replace(config, rows=rows)

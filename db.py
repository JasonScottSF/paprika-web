import os
import re
import sqlite3
import datetime
import functools
from pathlib import Path
from typing import Optional

# ── Path resolution ───────────────────────────────────────────────────────────
# Docker sets PAPRIKA_DATA_DIR; otherwise auto-detect macOS location.

_ENV_DIR = os.environ.get("PAPRIKA_DATA_DIR")

if _ENV_DIR:
    _DATA_DIR = Path(_ENV_DIR)
else:
    _DATA_DIR = (
        Path.home()
        / "Library"
        / "Group Containers"
        / "72KVKW69K8.com.hindsightlabs.paprika.mac.v3"
        / "Data"
    )

DB_PATH = _DATA_DIR / "Database" / "Paprika.sqlite"
PHOTOS_DIR = _DATA_DIR / "Photos"

_CD_EPOCH = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)


def _cd_to_date(ts) -> Optional[datetime.date]:
    if ts is None:
        return None
    return (_CD_EPOCH + datetime.timedelta(seconds=float(ts))).date()


def _connect():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Paprika database not found at {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _photo_url(recipe_uid: Optional[str], photo: Optional[str]) -> Optional[str]:
    if not photo or not recipe_uid:
        return None
    filename = photo if "." in photo else photo + ".jpg"
    return f"/photos/{recipe_uid}/{filename}"


def _enrich(row) -> dict:
    d = dict(row)
    d["photo_url"] = _photo_url(d.get("ZUID"), d.get("ZPHOTOLARGE") or d.get("ZPHOTO"))
    d["thumb_url"] = _photo_url(d.get("ZUID"), d.get("ZPHOTO"))
    d["categories_list"] = [c for c in (d.get("categories") or "").split("||") if c]
    src = d.get("ZSOURCEURL") or ""
    try:
        from urllib.parse import urlparse
        d["source_domain"] = urlparse(src).netloc.replace("www.", "") if src else (d.get("ZSOURCE") or "")
    except Exception:
        d["source_domain"] = d.get("ZSOURCE") or ""
    return d


# ── Ingredient classification ─────────────────────────────────────────────────

MEATS = frozenset({
    "beef", "chicken", "pork", "lamb", "turkey", "duck", "veal", "bison",
    "venison", "salmon", "tuna", "tilapia", "cod", "halibut", "shrimp",
    "crab", "lobster", "clam", "oyster", "mussel", "anchovy", "bacon",
    "ham", "prosciutto", "pancetta", "chorizo", "sausage", "pepperoni",
    "salami", "steak", "ribs", "brisket", "tenderloin", "fillet", "filet",
    "breast", "thigh", "wing", "drumstick", "fish", "seafood", "meatball",
    "burger", "kielbasa", "bratwurst", "liver", "scallop", "squid",
    "octopus", "catfish", "trout", "sardine", "herring", "pulled pork",
    "short rib", "oxtail", "rabbit", "goat", "elk", "boar", "ground beef",
    "ground pork", "ground turkey", "ground chicken", "ground meat",
    "rotisserie", "prawn", "langoustine",
})

VEGETABLES = frozenset({
    "onion", "garlic", "carrot", "celery", "broccoli", "spinach", "kale",
    "arugula", "lettuce", "romaine", "chard", "collard", "tomato", "pepper",
    "zucchini", "squash", "cucumber", "mushroom", "potato", "sweet potato",
    "yam", "corn", "pea", "bean", "lentil", "asparagus", "artichoke",
    "avocado", "beet", "bok choy", "cabbage", "cauliflower", "eggplant",
    "fennel", "leek", "parsnip", "radish", "turnip", "scallion", "shallot",
    "green bean", "brussels sprout", "edamame", "okra", "radicchio",
    "watercress", "endive", "celeriac", "kohlrabi", "rutabaga", "jicama",
    "taro", "nori", "seaweed", "chile", "chili", "jalapeño", "jalapeno",
    "serrano", "habanero", "poblano", "bell pepper", "capsicum",
    "vegetable", "veggie", "greens", "herb",
})


def classify_ingredient(name: str) -> tuple[bool, bool]:
    lower = name.lower()
    is_meat = any(m in lower for m in MEATS)
    is_veg = any(v in lower for v in VEGETABLES)
    return is_meat, is_veg


def validate_ingredients(ingredients: list[str]) -> dict:
    has_meat = any(classify_ingredient(i)[0] for i in ingredients)
    has_veg = any(classify_ingredient(i)[1] for i in ingredients)
    errors = []
    if len(ingredients) < 3:
        errors.append(f"Add at least {3 - len(ingredients)} more ingredient(s)")
    if not has_meat:
        errors.append("Include at least one meat or protein")
    if not has_veg:
        errors.append("Include at least one vegetable")
    return {
        "valid": not errors,
        "errors": errors,
        "has_meat": has_meat,
        "has_veg": has_veg,
        "count": len(ingredients),
    }


# ── Ingredient index (built once, cached) ─────────────────────────────────────

_STRIP_QTY = re.compile(
    r"^[\d¼½¾⅓⅔⅛⅜⅝⅞\s,./\-\(\)]+\s*"
    r"(?:cups?|tbsps?|tablespoons?|tsps?|teaspoons?|lbs?|pounds?|ozs?|ounces?"
    r"|grams?|g\b|kgs?|ml\b|liters?|litres?|pints?|quarts?|gallons?|cans?"
    r"|pkgs?|packages?|slices?|pieces?|cloves?|stalks?|heads?|bunches?|sprigs?"
    r"|large|medium|small|whole|pinch|dash|handful|bunch)\s*(?:of\s+)?",
    re.IGNORECASE,
)


def _clean_ingredient_line(line: str) -> str:
    line = line.strip()
    if not line or line.startswith("!"):
        return ""
    line = _STRIP_QTY.sub("", line)
    line = re.sub(r"\(.*?\)", "", line)
    line = line.split(",")[0].split(" or ")[0].strip()
    return line if len(line) > 2 else ""


@functools.lru_cache(maxsize=1)
def get_ingredient_index() -> list[str]:
    conn = _connect()
    rows = conn.execute(
        "SELECT ZINGREDIENTS FROM ZRECIPE WHERE ZINTRASH=0 AND ZINGREDIENTS IS NOT NULL"
    ).fetchall()
    conn.close()
    ingredients: set[str] = set()
    for row in rows:
        for line in (row[0] or "").splitlines():
            cleaned = _clean_ingredient_line(line)
            if cleaned:
                ingredients.add(cleaned.lower())
    return sorted(ingredients)


def autocomplete_ingredients(q: str, limit: int = 12) -> list[str]:
    if not q or len(q) < 2:
        return []
    q_lower = q.lower()
    index = get_ingredient_index()
    # Prefer starts-with, then contains
    starts = [i for i in index if i.startswith(q_lower)]
    contains = [i for i in index if q_lower in i and not i.startswith(q_lower)]
    return (starts + contains)[:limit]


# ── Recipe queries ────────────────────────────────────────────────────────────

_LIST_SELECT = """
    SELECT r.Z_PK, r.ZUID, r.ZNAME, r.ZPHOTO, r.ZPHOTOLARGE, r.ZRATING,
           r.ZTOTALTIME, r.ZPREPTIME, r.ZCOOKTIME, r.ZSERVINGS,
           r.ZONFAVORITES, r.ZSOURCE, r.ZSOURCEURL,
           GROUP_CONCAT(c.ZNAME, "||") AS categories
    FROM ZRECIPE r
    LEFT JOIN Z_12CATEGORIES jc ON jc.Z_12RECIPES = r.Z_PK
    LEFT JOIN ZRECIPECATEGORY c ON c.Z_PK = jc.Z_13CATEGORIES
    WHERE r.ZINTRASH = 0
"""

_SORT_MAP = {
    "rating": "r.ZRATING DESC, r.ZNAME",
    "recent": "r.ZCREATED DESC",
    "name": "r.ZNAME",
}


def get_recipes(
    category_pk: Optional[int] = None,
    favorites: bool = False,
    search: Optional[str] = None,
    sort: str = "name",
    ingredient: Optional[str] = None,
) -> list[dict]:
    conn = _connect()
    try:
        sql = _LIST_SELECT
        params: list = []

        if category_pk is not None:
            sql += " AND jc.Z_13CATEGORIES = ?"
            params.append(category_pk)
        if favorites:
            sql += " AND r.ZONFAVORITES = 1"
        if search:
            term = f"%{search}%"
            sql += " AND (r.ZNAME LIKE ? OR r.ZINGREDIENTS LIKE ?)"
            params += [term, term]
        if ingredient:
            sql += " AND LOWER(r.ZINGREDIENTS) LIKE ?"
            params.append(f"%{ingredient.lower()}%")

        order = _SORT_MAP.get(sort, "r.ZNAME")
        sql += f" GROUP BY r.Z_PK ORDER BY {order}"
        rows = conn.execute(sql, params).fetchall()
        return [_enrich(r) for r in rows]
    finally:
        conn.close()


def get_recipe(uid: str) -> Optional[dict]:
    conn = _connect()
    try:
        sql = """
            SELECT r.*, GROUP_CONCAT(c.ZNAME, "||") AS categories
            FROM ZRECIPE r
            LEFT JOIN Z_12CATEGORIES jc ON jc.Z_12RECIPES = r.Z_PK
            LEFT JOIN ZRECIPECATEGORY c ON c.Z_PK = jc.Z_13CATEGORIES
            WHERE r.ZUID = ?
            GROUP BY r.Z_PK
        """
        row = conn.execute(sql, [uid]).fetchone()
        return _enrich(row) if row else None
    finally:
        conn.close()


def get_categories() -> list[sqlite3.Row]:
    conn = _connect()
    try:
        sql = """
            SELECT c.Z_PK, c.ZNAME,
                   COUNT(DISTINCT r.Z_PK) AS count
            FROM ZRECIPECATEGORY c
            LEFT JOIN Z_12CATEGORIES jc ON jc.Z_13CATEGORIES = c.Z_PK
            LEFT JOIN ZRECIPE r ON r.Z_PK = jc.Z_12RECIPES AND r.ZINTRASH = 0
            GROUP BY c.Z_PK
            ORDER BY c.ZNAME
        """
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ── Ingredient suggestion ─────────────────────────────────────────────────────

def suggest_recipes(ingredients: list[str], mode: str = "best") -> list[dict]:
    if not ingredients:
        return []
    conn = _connect()
    try:
        def esc(s: str) -> str:
            return s.lower().replace("'", "''")

        like_parts = [f"LOWER(r.ZINGREDIENTS) LIKE '%{esc(i)}%'" for i in ingredients]
        score_cases = " + ".join(
            f"(CASE WHEN LOWER(r.ZINGREDIENTS) LIKE '%{esc(i)}%' THEN 1 ELSE 0 END)"
            for i in ingredients
        )

        if mode == "all":
            where = " AND ".join(like_parts)
        else:
            where = " OR ".join(like_parts)

        sql = f"""
            SELECT r.Z_PK, r.ZUID, r.ZNAME, r.ZPHOTO, r.ZPHOTOLARGE,
                   r.ZRATING, r.ZTOTALTIME, r.ZPREPTIME, r.ZCOOKTIME,
                   r.ZSERVINGS, r.ZINGREDIENTS, r.ZSOURCEURL, r.ZSOURCE,
                   ({score_cases}) AS match_score
            FROM ZRECIPE r
            WHERE r.ZINTRASH = 0 AND ({where})
            ORDER BY match_score DESC,
                     COALESCE(r.ZRATING, 0) DESC,
                     r.ZNAME
            LIMIT 60
        """
        rows = conn.execute(sql).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["photo_url"] = _photo_url(d.get("ZUID"), d.get("ZPHOTOLARGE") or d.get("ZPHOTO"))
            d["thumb_url"] = _photo_url(d.get("ZUID"), d.get("ZPHOTO"))
            ingr_text = (d.get("ZINGREDIENTS") or "").lower()
            d["matched"] = [i for i in ingredients if i.lower() in ingr_text]
            d["unmatched"] = [i for i in ingredients if i.lower() not in ingr_text]
            try:
                from urllib.parse import urlparse
                src = d.get("ZSOURCEURL") or ""
                d["source_domain"] = urlparse(src).netloc.replace("www.", "") if src else (d.get("ZSOURCE") or "")
            except Exception:
                d["source_domain"] = ""
            result.append(d)
        return result
    finally:
        conn.close()


# ── Meal planner ──────────────────────────────────────────────────────────────

def get_meals_for_week(week_start: datetime.date) -> dict:
    conn = _connect()
    try:
        start_ts = (
            datetime.datetime.combine(week_start, datetime.time.min, tzinfo=datetime.timezone.utc)
            - _CD_EPOCH
        ).total_seconds()
        end_ts = start_ts + 7 * 86400
        sql = """
            SELECT m.ZDATE, m.ZNAME, m.ZORDERFLAG,
                   mt.ZNAME AS meal_type, mt.Z_PK AS type_pk,
                   r.ZNAME AS recipe_name, r.ZPHOTO, r.ZPHOTOLARGE,
                   r.ZUID AS recipe_uid, r.ZRATING
            FROM ZMEAL m
            LEFT JOIN ZMEALTYPE mt ON mt.Z_PK = m.ZTYPE
            LEFT JOIN ZRECIPE r ON r.Z_PK = m.ZRECIPE
            WHERE m.ZDATE >= ? AND m.ZDATE < ?
            ORDER BY m.ZDATE, mt.Z_PK, m.ZORDERFLAG
        """
        rows = conn.execute(sql, [start_ts, end_ts]).fetchall()
        result: dict = {}
        for row in rows:
            date = _cd_to_date(row["ZDATE"])
            mtype = row["meal_type"] or "Other"
            result.setdefault(date, {}).setdefault(mtype, []).append(dict(row))
        return result
    finally:
        conn.close()


# ── Grocery lists ─────────────────────────────────────────────────────────────

def get_grocery_lists() -> list[sqlite3.Row]:
    conn = _connect()
    try:
        sql = """
            SELECT gl.Z_PK, gl.ZNAME, gl.ZISDEFAULT,
                   COUNT(gi.Z_PK) AS total,
                   SUM(gi.ZPURCHASED) AS purchased
            FROM ZGROCERYLIST gl
            LEFT JOIN ZGROCERYITEM gi ON gi.ZLIST = gl.Z_PK
            GROUP BY gl.Z_PK
            ORDER BY gl.ZISDEFAULT DESC, gl.ZNAME
        """
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def get_grocery_items(list_pk: int) -> list[sqlite3.Row]:
    conn = _connect()
    try:
        sql = """
            SELECT gi.*, ga.ZNAME AS aisle_name
            FROM ZGROCERYITEM gi
            LEFT JOIN ZGROCERYAISLE ga ON ga.Z_PK = gi.ZAISLE
            WHERE gi.ZLIST = ?
            ORDER BY gi.ZPURCHASED, gi.ZAISLENAME NULLS LAST, gi.ZORDERFLAG, gi.ZNAME
        """
        return conn.execute(sql, [list_pk]).fetchall()
    finally:
        conn.close()

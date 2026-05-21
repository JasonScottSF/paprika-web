import sqlite3
import datetime
from pathlib import Path
from typing import Optional

PAPRIKA_GROUP_CONTAINER = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "72KVKW69K8.com.hindsightlabs.paprika.mac.v3"
    / "Data"
)

DB_PATH = PAPRIKA_GROUP_CONTAINER / "Database" / "Paprika.sqlite"
PHOTOS_DIR = PAPRIKA_GROUP_CONTAINER / "Photos"

# Core Data timestamps are seconds since 2001-01-01 UTC
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


# ── recipes ──────────────────────────────────────────────────────────────────

_RECIPE_LIST_SELECT = """
    SELECT r.Z_PK, r.ZUID, r.ZNAME, r.ZPHOTO, r.ZPHOTOLARGE, r.ZRATING,
           r.ZTOTALTIME, r.ZPREPTIME, r.ZCOOKTIME, r.ZSERVINGS,
           r.ZONFAVORITES, r.ZDIFFICULTY,
           GROUP_CONCAT(c.ZNAME, '||') AS categories
    FROM ZRECIPE r
    LEFT JOIN Z_12CATEGORIES jc ON jc.Z_12RECIPES = r.Z_PK
    LEFT JOIN ZRECIPECATEGORY c ON c.Z_PK = jc.Z_13CATEGORIES
    WHERE r.ZINTRASH = 0
"""


def get_recipes(
    category_pk: Optional[int] = None,
    favorites: bool = False,
    search: Optional[str] = None,
) -> list[sqlite3.Row]:
    conn = _connect()
    try:
        sql = _RECIPE_LIST_SELECT
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

        sql += " GROUP BY r.Z_PK ORDER BY r.ZNAME"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def get_recipe(uid: str) -> Optional[sqlite3.Row]:
    conn = _connect()
    try:
        sql = """
            SELECT r.*,
                   GROUP_CONCAT(c.ZNAME, '||') AS categories
            FROM ZRECIPE r
            LEFT JOIN Z_12CATEGORIES jc ON jc.Z_12RECIPES = r.Z_PK
            LEFT JOIN ZRECIPECATEGORY c ON c.Z_PK = jc.Z_13CATEGORIES
            WHERE r.ZUID = ?
            GROUP BY r.Z_PK
        """
        return conn.execute(sql, [uid]).fetchone()
    finally:
        conn.close()


# ── categories ───────────────────────────────────────────────────────────────

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


# ── meal planner ─────────────────────────────────────────────────────────────

def get_meals_for_week(week_start: datetime.date) -> dict:
    """Return meals keyed by (date, meal_type_name)."""
    conn = _connect()
    try:
        # Convert date range to Core Data timestamps
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

        # Build dict: date → {meal_type → [entries]}
        result: dict = {}
        for row in rows:
            date = _cd_to_date(row["ZDATE"])
            mtype = row["meal_type"] or "Other"
            result.setdefault(date, {}).setdefault(mtype, []).append(dict(row))
        return result
    finally:
        conn.close()


# ── grocery lists ─────────────────────────────────────────────────────────────

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

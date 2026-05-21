import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db

app = FastAPI(title="Paprika Web")

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── photo serving ─────────────────────────────────────────────────────────────

@app.get("/photos/{recipe_uid}/{filename}")
async def serve_photo(recipe_uid: str, filename: str):
    path = db.PHOTOS_DIR / recipe_uid / filename
    if not path.exists():
        # Try with .jpg extension if not present
        path = db.PHOTOS_DIR / recipe_uid / (filename + ".jpg")
    if not path.exists():
        return RedirectResponse("/static/no-photo.svg")
    return FileResponse(path)


# ── helpers ───────────────────────────────────────────────────────────────────

def _photo_url(recipe_uid: str, photo: Optional[str]) -> Optional[str]:
    if not photo or not recipe_uid:
        return None
    filename = photo if "." in photo else photo + ".jpg"
    return f"/photos/{recipe_uid}/{filename}"


def _enrich(row) -> dict:
    d = dict(row)
    d["photo_url"] = _photo_url(d.get("ZUID"), d.get("ZPHOTOLARGE") or d.get("ZPHOTO"))
    d["thumb_url"] = _photo_url(d.get("ZUID"), d.get("ZPHOTO"))
    d["categories_list"] = [c for c in (d.get("categories") or "").split("||") if c]
    return d


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=RedirectResponse)
async def index():
    return RedirectResponse("/recipes")


@app.get("/recipes", response_class=HTMLResponse)
async def recipes(
    request: Request,
    q: Optional[str] = Query(None),
    cat: Optional[int] = Query(None),
    favorites: bool = Query(False),
):
    categories = [dict(r) for r in db.get_categories()]
    rows = db.get_recipes(category_pk=cat, favorites=favorites, search=q)
    recipe_list = [_enrich(r) for r in rows]

    ctx = {
        "request": request,
        "recipes": recipe_list,
        "categories": categories,
        "active_cat": cat,
        "favorites": favorites,
        "q": q or "",
        "count": len(recipe_list),
    }

    # HTMX partial response
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/recipe_cards.html", ctx)

    return templates.TemplateResponse("recipes.html", ctx)


@app.get("/recipes/{uid}", response_class=HTMLResponse)
async def recipe_detail(request: Request, uid: str):
    row = db.get_recipe(uid)
    if not row:
        return HTMLResponse("Recipe not found", status_code=404)
    recipe = _enrich(row)

    # Parse ingredients and directions into lists
    recipe["ingredients_list"] = [
        line for line in (recipe.get("ZINGREDIENTS") or "").splitlines() if line.strip()
    ]
    recipe["directions_list"] = [
        p.strip() for p in (recipe.get("ZDIRECTIONS") or "").split("\n\n") if p.strip()
    ]

    return templates.TemplateResponse("recipe.html", {"request": request, "recipe": recipe})


@app.get("/menus", response_class=HTMLResponse)
async def menus(
    request: Request,
    week: Optional[str] = Query(None),
):
    if week:
        try:
            week_start = datetime.date.fromisoformat(week)
        except ValueError:
            week_start = _this_monday()
    else:
        week_start = _this_monday()

    week_dates = [week_start + datetime.timedelta(days=i) for i in range(7)]
    prev_week = (week_start - datetime.timedelta(days=7)).isoformat()
    next_week = (week_start + datetime.timedelta(days=7)).isoformat()

    meal_data = db.get_meals_for_week(week_start)
    meal_types = ["Breakfast", "Lunch", "Dinner", "Snacks"]

    return templates.TemplateResponse("menus.html", {
        "request": request,
        "week_dates": week_dates,
        "meal_data": meal_data,
        "meal_types": meal_types,
        "prev_week": prev_week,
        "next_week": next_week,
        "week_label": _week_label(week_start),
        "now_date": datetime.date.today().isoformat(),
    })


@app.get("/grocery", response_class=HTMLResponse)
async def grocery(
    request: Request,
    list_id: Optional[int] = Query(None),
):
    lists = [dict(r) for r in db.get_grocery_lists()]
    active_list = list_id or (lists[0]["Z_PK"] if lists else None)
    items = []

    if active_list:
        raw = db.get_grocery_items(active_list)
        # Group by aisle
        grouped: dict = {}
        for item in raw:
            aisle = item["aisle_name"] or item["ZAISLENAME"] or "Other"
            grouped.setdefault(aisle, []).append(dict(item))
        items = sorted(grouped.items())

    return templates.TemplateResponse("grocery.html", {
        "request": request,
        "lists": lists,
        "active_list": active_list,
        "items": items,
    })


def _this_monday() -> datetime.date:
    today = datetime.date.today()
    return today - datetime.timedelta(days=today.weekday())


def _week_label(week_start: datetime.date) -> str:
    end = week_start + datetime.timedelta(days=6)
    if week_start.month == end.month:
        return f"{week_start.strftime('%B %-d')}–{end.day}, {end.year}"
    return f"{week_start.strftime('%b %-d')} – {end.strftime('%b %-d, %Y')}"

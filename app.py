import urllib.parse
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db

app = FastAPI(title="Paprika Web")

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── Jinja2 filters ────────────────────────────────────────────────────────────

def _stars_filter(rating):
    r = int(rating or 0)
    return "★" * r + "☆" * (5 - r)

templates.env.filters["stars"] = _stars_filter
templates.env.globals["urlencode"] = urllib.parse.quote


# ── Photo serving ─────────────────────────────────────────────────────────────

@app.get("/photos/{recipe_uid}/{filename}")
async def serve_photo(recipe_uid: str, filename: str):
    path = db.PHOTOS_DIR / recipe_uid / filename
    if not path.exists():
        path = db.PHOTOS_DIR / recipe_uid / (filename + ".jpg")
    if not path.exists():
        return RedirectResponse("/static/no-photo.svg")
    return FileResponse(path)


# ── Autocomplete API ─────────────────────────────────────────────────────────

@app.get("/api/autocomplete")
async def autocomplete(q: str = Query("")):
    results = db.autocomplete_ingredients(q)
    return JSONResponse([{"name": r} for r in results])


# ── Redirect root ─────────────────────────────────────────────────────────────

@app.get("/", response_class=RedirectResponse)
async def index():
    return RedirectResponse("/recipes")


# ── Recipes ───────────────────────────────────────────────────────────────────

@app.get("/recipes", response_class=HTMLResponse)
async def recipes(
    request: Request,
    q: Optional[str] = Query(None),
    cat: Optional[int] = Query(None),
    favorites: bool = Query(False),
    sort: str = Query("name"),
    view: str = Query("list"),
):
    categories = [dict(r) for r in db.get_categories()]
    recipe_list = db.get_recipes(category_pk=cat, favorites=favorites, search=q, sort=sort)

    ctx = {
        "request": request,
        "recipes": recipe_list,
        "categories": categories,
        "active_cat": cat,
        "favorites": favorites,
        "sort": sort,
        "view": view,
        "q": q or "",
        "count": len(recipe_list),
        "total": sum(c["count"] for c in categories),
    }

    if request.headers.get("HX-Request"):
        tmpl = "partials/recipe_list.html" if view == "list" else "partials/recipe_cards.html"
        return templates.TemplateResponse(tmpl, ctx)

    return templates.TemplateResponse("recipes.html", ctx)


@app.get("/recipes/{uid}", response_class=HTMLResponse)
async def recipe_detail(request: Request, uid: str):
    recipe = db.get_recipe(uid)
    if not recipe:
        return HTMLResponse("Recipe not found", status_code=404)

    recipe["ingredients_list"] = [
        line for line in (recipe.get("ZINGREDIENTS") or "").splitlines() if line.strip()
    ]
    recipe["directions_list"] = [
        p.strip() for p in (recipe.get("ZDIRECTIONS") or "").split("\n\n") if p.strip()
    ]

    return templates.TemplateResponse("recipe.html", {"request": request, "recipe": recipe})


# ── Ingredient browsing ──────────────────────────────────────────────────────

@app.get("/ingredient/{name}", response_class=HTMLResponse)
async def ingredient_detail(request: Request, name: str):
    decoded = urllib.parse.unquote(name)
    recipe_list = db.get_recipes(ingredient=decoded, sort="rating")
    categories = [dict(r) for r in db.get_categories()]
    return templates.TemplateResponse("ingredient.html", {
        "request": request,
        "ingredient": decoded,
        "recipes": recipe_list,
        "categories": categories,
        "count": len(recipe_list),
        "total": sum(c["count"] for c in categories),
    })


# ── Ingredient finder ─────────────────────────────────────────────────────────

@app.get("/suggest", response_class=HTMLResponse)
async def suggest(
    request: Request,
    ingredients: list[str] = Query(default=[]),
    mode: str = Query("best"),
):
    categories = [dict(r) for r in db.get_categories()]
    validation = db.validate_ingredients(ingredients) if ingredients else None
    results = []
    if ingredients and validation and validation["valid"]:
        results = db.suggest_recipes(ingredients, mode=mode)

    ctx = {
        "request": request,
        "ingredients": ingredients,
        "mode": mode,
        "validation": validation,
        "results": results,
        "categories": categories,
        "total": sum(c["count"] for c in categories),
    }

    if request.headers.get("HX-Request") and "HX-Target" in request.headers:
        return templates.TemplateResponse("partials/suggest_results.html", ctx)

    return templates.TemplateResponse("suggest.html", ctx)



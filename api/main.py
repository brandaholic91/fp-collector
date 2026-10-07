import asyncpg
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config import settings
from limiter import limiter
from routes import events, stats


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = await asyncpg.create_pool(settings.database_url)
    yield
    await app.state.db_pool.close()


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)

app.include_router(events.router)
app.include_router(stats.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def landing():
    return FileResponse("static/landing/index.html")


@app.get("/adatkezeles")
async def privacy():
    return FileResponse("static/landing/privacy.html")


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.svg", media_type="image/svg+xml")


@app.get("/robots.txt", include_in_schema=False)
async def robots():
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /dashboard\n"
        "Disallow: /api/\n"
        "Disallow: /static/\n"
        "\n"
        "Sitemap: https://fp.growthframe.hu/sitemap.xml\n"
    )


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    return PlainTextResponse(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url>\n"
        "    <loc>https://fp.growthframe.hu/</loc>\n"
        "    <changefreq>weekly</changefreq>\n"
        "    <priority>1.0</priority>\n"
        "  </url>\n"
        "</urlset>\n",
        media_type="application/xml",
    )


@app.get("/dashboard")
async def dashboard():
    return FileResponse("static/dashboard/index.html")

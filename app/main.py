import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.database import init_db
from app.core.rates import rates_service
from app.api.routes import router as api_router
from app.bot.bot_instance import start_bot_polling, stop_bot_polling

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

bot_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up Deal Auditor application...")
    await init_db()
    logger.info("Database initialized successfully.")
    
    # Warm up rates cache
    asyncio.create_task(rates_service.get_rates(force_refresh=False))

    # Initialize SotaVPN tunnel config if key provided
    if settings.SOTA_VPN_KEY:
        from app.core.vpn_config import generate_singbox_config_file
        cfg_path = Path("data/singbox_config.json")
        if generate_singbox_config_file(settings.SOTA_VPN_KEY, str(cfg_path)):
            logger.info(f"SotaVPN sing-box tunnel config generated at {cfg_path}")
    
    # Start bot polling if BOT_TOKEN is configured
    global bot_task
    if settings.BOT_TOKEN:
        logger.info("BOT_TOKEN provided. Launching Telegram Bot polling...")
        bot_task = asyncio.create_task(start_bot_polling())
    else:
        logger.warning(
            "BOT_TOKEN is not set in environment or .env. "
            "Running in standalone web / Mini App mode at http://localhost:8000"
        )
    
    yield
    
    # Shutdown
    logger.info("Shutting down Deal Auditor application...")
    if bot_task:
        await stop_bot_polling()
        bot_task.cancel()


app = FastAPI(
    title="Аудитор сделок (Deal Auditor)",
    description="Калькулятор чистой прибыли для продавцов цифровых товаров (Plati, Playerok, FunPay)",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(api_router)

# Mount Static directory
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    icon_file = static_dir / "favicon.svg"
    if icon_file.exists():
        return FileResponse(icon_file, media_type="image/svg+xml")
    return FileResponse(static_dir / "index.html")


@app.get("/")
async def serve_index():
    """Отдает Telegram Mini App интерфейс."""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Deal Auditor API is active. Web UI index.html not yet placed."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )

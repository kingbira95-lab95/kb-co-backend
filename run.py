import os
import uvicorn
from app.config import settings

if __name__ == "__main__":
    # Railway injects PORT automatically; fall back to 8000 for local dev
    port = int(os.getenv("PORT", settings.PORT))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=settings.ENVIRONMENT == "development",
        log_level="info",
        # Workers: Railway scales horizontally, so 1 worker per container is correct
        workers=1,
    )

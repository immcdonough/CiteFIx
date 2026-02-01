"""FastAPI application entry point for CiteFix."""

import tempfile
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routers import documents

# Create temp directory for file processing
TEMP_DIR = Path(tempfile.gettempdir()) / "citefix"
TEMP_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="CiteFix",
    description="Citation formatting, DOI resolution, and validation for Word documents",
    version="0.1.0",
)

# Set up templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Include routers
app.include_router(documents.router, prefix="/api", tags=["documents"])


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the main page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}


def run():
    """Run the application with uvicorn."""
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()

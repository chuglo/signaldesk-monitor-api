from __future__ import annotations
import uvicorn
from .main import create_app
from .settings import Settings
def main() -> None: uvicorn.run(create_app(settings=Settings()), host="0.0.0.0", port=8000)

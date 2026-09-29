"""Fixed presentation artifacts, protected by the application's access middleware."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import ROOT

router = APIRouter(prefix="/sprint-review")


@router.get("")
def sprint_review():
    path = ROOT / "docs" / "sprint-review.html"
    if not path.is_file():
        path = ROOT / "docs" / "public-overview.html"
    return FileResponse(path, media_type="text/html")


@router.get("/handout")
def sprint_handout():
    path = ROOT / "docs" / "sprint-review.pdf"
    if not path.is_file():
        raise HTTPException(404, "The internal meeting handout is not installed.")
    return FileResponse(path, media_type="application/pdf")

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.models import MatchAnalysis, MatchInput
from app.providers.orchestrator import get_orchestrator
from app.stats.engine import analyze_match

router = APIRouter(prefix="/matches", tags=["matches"])


@router.post("/analyze", response_model=MatchAnalysis)
async def analyze(input_data: MatchInput):
    orchestrator = get_orchestrator()
    match_data = await orchestrator.get_match_stats(input_data)
    analysis = analyze_match(match_data)
    return analysis

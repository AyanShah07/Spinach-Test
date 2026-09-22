"""Campaign analysis backed by grounded facts and a recoverable provider circuit."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from app.ai.context_builder import build_campaign_context
from app.ai.provider import AIResponse
from app.ai.service import AnalysisService
from app.core.exceptions import NotFoundError
from app.db.repositories import CampaignRepo

router = APIRouter(prefix="/campaigns", tags=["ai"])

class AnalyzeResponse(BaseModel):
    campaign_id: str
    analysis: AIResponse

async def get_session(request: Request):
    async with request.app.state.session_factory() as session:
        yield session

def get_effective_llm(request: Request):
    """Return user-specified LLM if provided in request headers, else app default."""
    ai_key = request.headers.get("x-ai-key", "").strip()
    ai_provider = (request.headers.get("x-ai-provider", "")).strip().lower()

    if ai_key:
        if ai_provider == "gemini":
            from app.ai.adapters.gemini_adapter import GeminiAdapter
            return GeminiAdapter(api_key=ai_key)
        if ai_provider == "groq":
            from app.ai.adapters.groq_adapter import GroqAdapter
            return GroqAdapter(api_key=ai_key)
        if ai_provider == "openrouter":
            from app.ai.adapters.openrouter_adapter import OpenRouterAdapter
            return OpenRouterAdapter(api_key=ai_key)

    return getattr(request.app.state, "llm", None)


async def analyze(campaign_id, request, session, prompt):
    repo = CampaignRepo(session)
    campaign = await repo.get(campaign_id)
    if campaign is None:
        raise NotFoundError("Campaign not found", code="campaign_not_found")
    metrics = await repo.metrics(campaign_id)
    context = build_campaign_context(
        {"id": campaign.id, "objective": campaign.objective, "channel": campaign.channel,
         "status": campaign.status, "audience_size": campaign.audience_size},
        [{"metric_name": m.metric_name, "value": m.value} for m in metrics])
    llm = get_effective_llm(request)
    response = await request.app.state.ai_service.analyze(llm, prompt, context)
    return AnalyzeResponse(campaign_id=campaign_id, analysis=response)

@router.post("/{campaign_id}/analyze", response_model=AnalyzeResponse)
async def analyze_campaign(campaign_id: str, request: Request, session=Depends(get_session)):
    return await analyze(campaign_id, request, session,
        "Analyze campaign performance using only the supplied aggregates. Suggest actionable improvements.")

@router.post("/{campaign_id}/recommend", response_model=AnalyzeResponse)
async def recommend_for_campaign(campaign_id: str, request: Request, session=Depends(get_session)):
    return await analyze(campaign_id, request, session,
        "Based only on the supplied metrics and objective, recommend the top three next actions.")

"""Dependency wiring.

The API layer asks for a service and gets one; it never constructs a repository,
a graph or an LLM provider itself. Swapping the JSONL store for a database in
Phase 6, the stub LLM for a real one, or an ungoverned graph for a governed one
in Phase 4, is a change to this module alone.
"""

from __future__ import annotations

import os
from functools import lru_cache

from app.config import get_settings
from app.repositories.analysis_repository import (
    AnalysisRepository,
    JsonlAnalysisRepository,
)
from app.repositories.claim_repository import ClaimRepository, JsonlClaimRepository
from app.repositories.review_queue_repository import (
    JsonlReviewQueueRepository,
    ReviewQueueRepository,
)
from app.services.claim_service import ClaimService
from app.services.intelligence_service import ClaimIntelligenceService
from app.services.review_service import ReviewService


@lru_cache
def get_claim_repository() -> ClaimRepository:
    settings = get_settings()
    return JsonlClaimRepository(settings.claims_store_path)


@lru_cache
def get_analysis_repository() -> AnalysisRepository:
    settings = get_settings()
    return JsonlAnalysisRepository(settings.analyses_store_path)


@lru_cache
def get_review_queue_repository() -> ReviewQueueRepository:
    settings = get_settings()
    return JsonlReviewQueueRepository(settings.review_queue_store_path)


def get_claim_service() -> ClaimService:
    return ClaimService(get_claim_repository())


def get_review_service() -> ReviewService:
    return ReviewService(
        claims=get_claim_repository(),
        queue=get_review_queue_repository(),
    )


@lru_cache
def _llm_provider():  # noqa: ANN202 - the protocol lives in llm.base
    """Build the configured provider ONCE, and share it.

    Phase 4A change. Before, the graph built its own provider and the service
    was told a provider *name* read separately from the environment — two
    sources of truth that could disagree, and neither of which knew the model.
    Now there is one instance: the graph narrates through it and the service
    reports its `name` and `model` in the analysis result.
    """
    from llm.factory import get_llm_provider

    return get_llm_provider()


@lru_cache
def _compiled_graph():  # noqa: ANN202 - LangGraph's compiled type is internal
    """Compile the graph once. Gates compile at import in Phase 4 for the same reason."""
    from graph.builder import build_claims_graph

    return build_claims_graph(llm=_llm_provider())


@lru_cache
def get_conversation_repository():  # noqa: ANN201 - the Protocol lives in conversation.store
    from conversation.store import JsonlConversationRepository

    settings = get_settings()
    return JsonlConversationRepository(settings.conversations_store_path)


@lru_cache
def _conversation_graph():  # noqa: ANN202 - LangGraph's compiled type is internal
    """Compile the conversational graph once, sharing the ONE provider instance.

    Same provider object the claims graph narrates through. Two instances would
    mean two reads of the environment that could disagree about which model is
    answering — the exact bug Phase 4A removed from the claims path.
    """
    from agents.conversation import ConversationAgent
    from graph.conversation_graph import build_conversation_graph

    return build_conversation_graph(agent=ConversationAgent(_llm_provider()))


def get_assistant_service():  # noqa: ANN201 - imported lazily to keep startup light
    from app.services.assistant_service import AssistantService

    return AssistantService(
        conversations=get_conversation_repository(),
        claims=get_claim_service(),
        graph=_conversation_graph(),
    )


def get_intelligence_service() -> ClaimIntelligenceService:
    provider = _llm_provider()
    return ClaimIntelligenceService(
        claims=get_claim_repository(),
        analyses=get_analysis_repository(),
        graph=_compiled_graph(),
        reviews=get_review_service(),
        llm_name=provider.name,
        llm_model=getattr(provider, "model", None),
    )

from __future__ import annotations

from watchtracker.recommendations.service import RecommendationService


class RecommendationJobManager:
    """Small app boundary for scheduling the persisted recommendation state machine."""

    def __init__(self, service: RecommendationService):
        self.service = service

    async def run(self, run_id: str, user_id: str) -> None:
        await self.service.generate(run_id, user_id)

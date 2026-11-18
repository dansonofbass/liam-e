"""Private browser views; proposing does not confirm a preference."""
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from db.accessors.preference_candidate import CandidateGone
from api.preferences import candidates
from api.routers.api.v1.preferences.route import PrivatePreferenceRoute

router = APIRouter(route_class=PrivatePreferenceRoute)


class CandidateProposeIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    refresh: bool = False


@router.get('', operation_id='preference_candidates_list')
async def listing(candidate_id: str | None = Query(default=None)) -> list[candidates.CandidateOut]:
    return await candidates.listing(candidate_id)


@router.post('/{candidate_id}/propose', operation_id='preference_candidate_propose')
async def propose(candidate_id: str, body: CandidateProposeIn) -> candidates.CandidateOut:
    try:
        return await candidates.propose(candidate_id, refresh=body.refresh)
    except CandidateGone:
        raise candidates.unavailable() from None

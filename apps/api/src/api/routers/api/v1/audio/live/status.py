"""Expose the test-only live switch only to the bound owner and origin."""
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from api.audio.live_access import live_allowed

router = APIRouter()


class LiveStatus(BaseModel):
    available: bool


@router.post('', operation_id='audio_live_status')
async def status(request: Request, response: Response) -> LiveStatus:
    response.headers['Cache-Control'] = 'no-store'
    return LiveStatus(available=live_allowed(request))

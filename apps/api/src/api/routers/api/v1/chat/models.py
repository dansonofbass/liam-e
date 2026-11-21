"""Chat model catalogue."""
from fastapi import APIRouter
from sqlalchemy.exc import SQLAlchemyError

from api.errors import refuse
from api.mail.models_catalog import ChatModelOut, list_effective_chat_models

router = APIRouter()
list_chat_models = list_effective_chat_models


@router.get('', operation_id='chat_models_list', summary='List available chat models')
async def chat_models_list() -> list[ChatModelOut]:
    """Return available models that support chat and function calls."""
    try:
        return await list_chat_models()
    except SQLAlchemyError:
        raise refuse(503, 'settings_unavailable', 'Die Einstellungen sind gerade nicht erreichbar.') from None

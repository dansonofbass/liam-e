"""Chat model catalogue."""
from fastapi import APIRouter
from api.mail.models_catalog import ChatModelOut, list_chat_models

router = APIRouter()


@router.get('', operation_id='chat_models_list', summary='List available chat models')
async def chat_models_list() -> list[ChatModelOut]:
    """Return available models that support chat and function calls."""
    return await list_chat_models()

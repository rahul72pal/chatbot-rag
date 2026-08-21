from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional, Dict, Any
from app.core.dependencies import get_current_user, get_optional_current_user, get_user_llm_config_service
from app.services.user_llm_config_service import UserLLMConfigService
from app.schemas.user_llm_config import (
    UserLLMConfigCreate,
    UserLLMConfigUpdate,
    UserLLMConfigResponse
)

router = APIRouter(prefix="/llm-config")

@router.get(
    "/status",
    status_code=status.HTTP_200_OK,
    summary="Get LLM configuration status",
    description="Returns whether the user has configured their LLM settings."
)
async def get_llm_config_status(
    current_user: Optional[dict] = Depends(get_optional_current_user),
    config_service: UserLLMConfigService = Depends(get_user_llm_config_service)
) -> Dict[str, Any]:
    if not current_user:
        return {"llm_configured": False, "has_config": False}
    user_id = current_user["id"]
    configs = await config_service.get_user_configs(user_id=user_id)
    has_config = len(configs) > 0 and bool(configs[0].get("api_key"))
    return {"llm_configured": has_config, "has_config": has_config}


@router.post(
    "",
    response_model=UserLLMConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new LLM configuration",
    description="Registers a new LLM configuration (standard provider or custom endpoint) for the authenticated user."
)
async def create_user_config(
    payload: UserLLMConfigCreate,
    current_user: dict = Depends(get_current_user),
    config_service: UserLLMConfigService = Depends(get_user_llm_config_service)
) -> UserLLMConfigResponse:
    user_id = current_user["id"]
    config = await config_service.create_config(user_id=user_id, payload=payload)
    return UserLLMConfigResponse(**config)


@router.get(
    "",
    response_model=List[UserLLMConfigResponse],
    status_code=status.HTTP_200_OK,
    summary="List all LLM configurations",
    description="Returns a list of all saved LLM configurations for the authenticated user, or empty list if unauthenticated."
)
async def list_user_configs(
    current_user: Optional[dict] = Depends(get_optional_current_user),
    config_service: UserLLMConfigService = Depends(get_user_llm_config_service)
) -> List[UserLLMConfigResponse]:
    if not current_user:
        return []
    user_id = current_user["id"]
    configs = await config_service.get_user_configs(user_id=user_id)
    return [UserLLMConfigResponse(**c) for c in configs]


@router.get(
    "/{config_id}",
    response_model=UserLLMConfigResponse,
    status_code=status.HTTP_200_OK,
    summary="Get configuration details",
    description="Retrieves details for a specific LLM configuration, with masked API key."
)
async def get_user_config_detail(
    config_id: str,
    current_user: dict = Depends(get_current_user),
    config_service: UserLLMConfigService = Depends(get_user_llm_config_service)
) -> UserLLMConfigResponse:
    user_id = current_user["id"]
    config = await config_service.get_config(config_id=config_id, user_id=user_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LLM Configuration not found or access denied."
        )
    return UserLLMConfigResponse(**config)


@router.put(
    "/{config_id}",
    response_model=UserLLMConfigResponse,
    status_code=status.HTTP_200_OK,
    summary="Update LLM configuration",
    description="Updates specific fields of an LLM configuration. Does not overwrite the API key if a masked key is supplied."
)
async def update_user_config(
    config_id: str,
    payload: UserLLMConfigUpdate,
    current_user: dict = Depends(get_current_user),
    config_service: UserLLMConfigService = Depends(get_user_llm_config_service)
) -> UserLLMConfigResponse:
    user_id = current_user["id"]
    config = await config_service.update_config(config_id=config_id, user_id=user_id, payload=payload)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LLM Configuration not found or update failed."
        )
    return UserLLMConfigResponse(**config)


@router.delete(
    "/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete LLM configuration",
    description="Removes a saved LLM configuration."
)
async def delete_user_config(
    config_id: str,
    current_user: dict = Depends(get_current_user),
    config_service: UserLLMConfigService = Depends(get_user_llm_config_service)
):
    user_id = current_user["id"]
    success = await config_service.delete_config(config_id=config_id, user_id=user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LLM Configuration not found or deletion failed."
        )
    return

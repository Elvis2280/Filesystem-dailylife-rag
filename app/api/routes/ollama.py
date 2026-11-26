"""Ollama status, installed models, and server-wide model preferences."""

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.validators import validate_image_type
from app.core.database import get_db
from app.models.ollama_model_preferences import OllamaModelPreferences
from app.schemas.ollama import (
    OllamaFileOcrResponse,
    OllamaModelInfo,
    OllamaModelPreferenceUpdate,
    OllamaPreferencesResponse,
    OllamaPreferencesUpdate,
    OllamaStatusResponse,
)
from app.services.ai.model_preferences import (
    EDITABLE_ROLES,
    ModelRole,
    effective_model_preferences,
    environment_model_name,
    get_model_name_async,
    save_model_preferences,
)
from app.services.ai.ollama_client import (
    OllamaClient,
    get_ollama_client,
)
from app.services.ai.model_names import model_is_available
from app.services.ocr.file_ocr_llm import extract_image_text

router = APIRouter(prefix="/ollama", tags=["Ollama"])
dev_router = APIRouter(prefix="/ollama", tags=["Ollama"])
logger = logging.getLogger("memory_rag.ollama_api")

_RECOMMENDED_MODELS = {role: environment_model_name(role) for role in ModelRole}


def _response_preferences(
    preferences: OllamaModelPreferences | None,
) -> OllamaPreferencesResponse:
    effective = effective_model_preferences(preferences)
    return OllamaPreferencesResponse(
        ocr=effective[ModelRole.OCR.value],
        translation=effective[ModelRole.TRANSLATION.value],
        embedding=effective[ModelRole.EMBEDDING.value],
        answer=effective[ModelRole.ANSWER.value],
        formatting=effective[ModelRole.FORMATTING.value],
        cleaning=effective[ModelRole.CLEANING.value],
        editable_roles=[role.value for role in EDITABLE_ROLES],
    )


async def _read_preferences(
    db: AsyncSession,
) -> OllamaModelPreferences | None:
    try:
        return await db.scalar(
            select(OllamaModelPreferences).where(OllamaModelPreferences.id == 1)
        )
    except SQLAlchemyError as exc:
        logger.exception("Could not read Ollama model preferences")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model preference database is unavailable",
        ) from exc


def _role_eligible(role: ModelRole, capabilities: set[str]) -> bool:
    if role == ModelRole.OCR:
        return {"vision", "completion"}.issubset(capabilities)
    if role == ModelRole.EMBEDDING:
        return "embedding" in capabilities
    return "completion" in capabilities


async def _model_info(
    record: dict[str, Any],
    selected_models: dict[str, str],
    ollama: OllamaClient,
    semaphore: asyncio.Semaphore,
) -> OllamaModelInfo | None:
    name = record.get("name")
    if not isinstance(name, str) or not name:
        return None

    capabilities: list[str] = []
    detail_record: dict[str, Any] = {}
    try:
        async with semaphore:
            detail_record = await ollama.show_model(name)
        raw_capabilities = detail_record.get("capabilities", [])
        if isinstance(raw_capabilities, list):
            capabilities = [
                value for value in raw_capabilities if isinstance(value, str)
            ]
    except (httpx.HTTPError, RuntimeError, ValueError):
        # Keep the installed model visible if its metadata endpoint is
        # unavailable; it will have no role eligibility until metadata works.
        pass

    capability_set = set(capabilities)
    selected_roles = [
        role_name
        for role_name, selected_name in selected_models.items()
        if selected_name == name
    ]
    details = record.get("details")
    details = details if isinstance(details, dict) else {}
    shown_details = detail_record.get("details")
    if isinstance(shown_details, dict):
        details = {**details, **shown_details}

    return OllamaModelInfo(
        name=name,
        size=record.get("size") if isinstance(record.get("size"), int) else None,
        digest=record.get("digest") if isinstance(record.get("digest"), str) else None,
        modified_at=(
            record.get("modified_at")
            if isinstance(record.get("modified_at"), str)
            else None
        ),
        family=(
            details.get("family") if isinstance(details.get("family"), str) else None
        ),
        parameter_size=(
            details.get("parameter_size")
            if isinstance(details.get("parameter_size"), str)
            else None
        ),
        quantization_level=(
            details.get("quantization_level")
            if isinstance(details.get("quantization_level"), str)
            else None
        ),
        capabilities=capabilities,
        eligible_roles=[
            role.value for role in ModelRole if _role_eligible(role, capability_set)
        ],
        selected_roles=selected_roles,
        recommended_roles=[
            role.value
            for role, recommended_name in _RECOMMENDED_MODELS.items()
            if recommended_name == name
        ],
    )


@router.get(
    "/status", response_model=OllamaStatusResponse, status_code=status.HTTP_200_OK
)
async def ollama_status(
    ollama: OllamaClient = Depends(get_ollama_client),
    db: AsyncSession = Depends(get_db),
) -> OllamaStatusResponse:
    """Return Ollama connectivity, installed models, and current selections."""
    preferences = await _read_preferences(db)
    selected_models = effective_model_preferences(preferences)

    health = await ollama.health_check()
    if not health.is_reachable:
        return OllamaStatusResponse(
            is_reachable=False,
            available_models=[],
            models=[],
            selected_models=selected_models,
        )

    try:
        records = await ollama.list_models()
    except httpx.HTTPError:
        return OllamaStatusResponse(
            is_reachable=False,
            available_models=[],
            models=[],
            selected_models=selected_models,
        )

    semaphore = asyncio.Semaphore(6)
    model_results = await asyncio.gather(
        *(_model_info(record, selected_models, ollama, semaphore) for record in records)
    )
    models = [model for model in model_results if model is not None]
    return OllamaStatusResponse(
        is_reachable=True,
        available_models=sorted({model.name for model in models}),
        models=models,
        selected_models=selected_models,
    )


@router.get("/preferences", response_model=OllamaPreferencesResponse)
async def get_ollama_preferences(
    db: AsyncSession = Depends(get_db),
) -> OllamaPreferencesResponse:
    preferences = await _read_preferences(db)
    return _response_preferences(preferences)


async def _update_model_preferences(
    updates: dict[ModelRole, str],
    ollama: OllamaClient,
    db: AsyncSession,
) -> OllamaPreferencesResponse:
    if not updates or any(not value for value in updates.values()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one non-empty editable model preference",
        )
    if any(role not in EDITABLE_ROLES for role in updates):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One or more destinations cannot be edited",
        )
    if any(len(value) > 255 for value in updates.values()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Model names must be at most 255 characters long",
        )

    try:
        health = await ollama.health_check()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        logger.exception("Could not check Ollama before updating model preferences")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama server is not reachable",
        ) from exc
    if not health.is_reachable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama server is not reachable",
        )

    installed_models = set(health.available_models)
    for role, model_name in updates.items():
        if not model_is_available(model_name, installed_models):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Model '{model_name}' is not installed on the Ollama server",
            )
        try:
            model_details = await ollama.show_model(model_name)
        except (httpx.HTTPError, RuntimeError, ValueError, TypeError) as exc:
            logger.exception(
                "Could not read Ollama capabilities for model %s", model_name
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not read capabilities for model '{model_name}'",
            ) from exc
        raw_capabilities = model_details.get("capabilities")
        if not isinstance(raw_capabilities, list) or any(
            not isinstance(value, str) for value in raw_capabilities
        ):
            logger.warning(
                "Ollama returned malformed capabilities for model %s", model_name
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not read capabilities for model '{model_name}'",
            )
        capabilities = set(raw_capabilities)
        if not _role_eligible(role, capabilities):
            needed = (
                "vision and text generation"
                if role == ModelRole.OCR
                else "text generation"
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Model '{model_name}' does not advertise {needed} capability",
            )

    try:
        preferences = await save_model_preferences(updates, db)
    except SQLAlchemyError as exc:
        logger.exception("Could not save Ollama model preferences")
        try:
            await db.rollback()
        except SQLAlchemyError:
            logger.exception("Could not roll back the Ollama preference update")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model preference database is unavailable",
        ) from exc
    if preferences is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama model preferences are not initialized",
        )

    return _response_preferences(preferences)


@router.patch("/preferences", response_model=OllamaPreferencesResponse)
async def update_ollama_preferences(
    update: OllamaPreferencesUpdate,
    ollama: OllamaClient = Depends(get_ollama_client),
    db: AsyncSession = Depends(get_db),
) -> OllamaPreferencesResponse:
    updates = {
        ModelRole(key): value.strip()
        for key, value in update.model_dump(exclude_unset=True).items()
        if value is not None
    }
    return await _update_model_preferences(updates, ollama, db)


@router.patch("/preferences/model", response_model=OllamaPreferencesResponse)
async def update_ollama_model_preference(
    update: OllamaModelPreferenceUpdate,
    ollama: OllamaClient = Depends(get_ollama_client),
    db: AsyncSession = Depends(get_db),
) -> OllamaPreferencesResponse:
    """Select the installed Ollama model for one task."""
    destination = update.destination
    role = ModelRole.ANSWER if destination == "agent" else ModelRole(destination)
    return await _update_model_preferences({role: update.model}, ollama, db)


@dev_router.post(
    "/ocr", response_model=OllamaFileOcrResponse, status_code=status.HTTP_200_OK
)
async def ollama_ocr(
    file: UploadFile = File(...),
    ollama: OllamaClient = Depends(get_ollama_client),
):
    """Run a development-only OCR test against the currently selected model."""
    health_status = await ollama.health_check()
    if not health_status.is_reachable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama server is not reachable",
        )

    validate_image_type(file)
    file_received = await file.read()

    try:
        model_name = await get_model_name_async(ModelRole.OCR)
        ocr_result = await asyncio.to_thread(
            extract_image_text, file_received, model_name=model_name
        )
        return OllamaFileOcrResponse(
            file_text=ocr_result,
            ollama_model=model_name,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

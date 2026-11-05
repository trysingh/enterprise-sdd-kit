from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.features.f000_reference.schemas import Greeting
from app.features.f000_reference.service import greet
from app.features.f000_reference.settings import get_reference_settings

router = APIRouter(prefix="/reference", tags=["reference"])

Name = Annotated[str, Query(min_length=1, max_length=40, pattern=r"\S")]  # SEC-03: validate at the boundary


@router.get("/greeting", response_model=Greeting)
def get_greeting(name: Name) -> Greeting:
    return Greeting(message=greet(name, get_reference_settings().greeting_word))

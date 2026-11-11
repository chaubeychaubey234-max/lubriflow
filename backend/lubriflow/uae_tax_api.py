from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from .auth import staff, role
from .uae_vat import calculate

router = APIRouter(prefix='/api/uae-vat')


class Preview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    taxDate: str
    side: str
    trn: str = Field(max_length=15)
    lines: list[dict] = Field(min_length=1, max_length=100)


@router.post('/preview')
def preview(body: Preview, user=Depends(staff)):
    role(user, 'admin', 'finance')
    return calculate(body.model_dump())

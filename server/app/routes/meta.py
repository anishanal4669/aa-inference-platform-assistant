from fastapi import APIRouter, Depends

from ..auth import Principal, require_key
from ..metering import ledger
from ..registry import load_registry

router = APIRouter()


@router.get("/v1/models")
async def models() -> dict:
    return {
        "data": [
            {
                "id": s.id,
                "description": s.description,
                "context_window": s.context_window,
                "max_output_tokens": s.max_output_tokens,
                "pricing": {
                    "input_per_mtok": s.input_price_per_mtok,
                    "output_per_mtok": s.output_price_per_mtok,
                },
            }
            for s in load_registry().list()
        ]
    }


@router.get("/v1/usage")
async def usage(limit: int = 25, principal: Principal = Depends(require_key)) -> dict:
    return {
        "totals": ledger.totals(principal.owner),
        "recent": ledger.recent(principal.owner, limit=limit),
    }


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}

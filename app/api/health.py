from fastapi import APIRouter, HTTPException
from app.services.supabase_service import get_supabase_client

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.get("/health/db")
async def health_db_check():
    try:
        client = get_supabase_client()
        client.table("users").select("id").limit(1).execute()
        return {"status": "ok", "database": "connected"}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)}")

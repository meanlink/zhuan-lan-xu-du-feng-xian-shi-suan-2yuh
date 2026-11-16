from sqlalchemy import select, func
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from src.config.database import get_db
from src.config.settings import ARTIFACT_DIR
from src.middlewares.auth import current_user, can_write
from src.models import BlindCase, Dataset, Job, Report, Audit
from src.services.business import metadata
from src.services.audit import record
router = APIRouter()


@router.get('/meta')
def meta(): return metadata()


@router.get('/overview')
def overview(db=Depends(get_db), user=Depends(current_user)):
    return {
        'datasets': db.scalar(select(func.count()).select_from(Dataset)),
        'records': sum(len(d.records) for d in db.scalars(select(Dataset))),
        'jobs': db.scalar(select(func.count()).select_from(Job)),
        'approved': db.scalar(select(func.count()).select_from(Job).where(Job.approved == True)),
        'reports': db.scalar(select(func.count()).select_from(Report)),
        'blind_cases': db.scalar(select(func.count()).select_from(BlindCase)),
    }


@router.get('/audits')
def audits(db=Depends(get_db), user=Depends(current_user)):
    return [{'id': a.id, 'actor': a.actor, 'action': a.action, 'detail': a.detail, 'at': a.at} for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(50))]

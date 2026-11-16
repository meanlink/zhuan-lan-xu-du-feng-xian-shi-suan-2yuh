from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from src.config.database import get_db
from src.middlewares.auth import current_user, can_write, admin_only
from src.models import BlindCase, Dataset, Job
from src.services import blind, jobs as job_service
from src.services.audit import record
from src.utils.serialization import job_dict
router = APIRouter(prefix='/blind-cases')


class CaseInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source: str = Field(default='manual.json', max_length=200)
    records: list[dict] = Field(min_length=5, max_length=5000)


class CandidateInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    params: dict = Field(default_factory=dict)


class SelectInput(BaseModel):
    job_id: int


def _case(db, case_id):
    return blind.get_case(db, case_id)


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return [blind.case_dict(db, c) for c in db.scalars(select(BlindCase).order_by(BlindCase.id.desc()).limit(100))]


@router.post('', status_code=201)
def create(data: CaseInput, db=Depends(get_db), u=Depends(admin_only)):
    case = blind.create_case(db, data, u)
    record(db, u.email, 'blind.case.create', {'id': case.id, 'split': case.split.get('seed'), 'development': case.development_dataset_id, 'sealed': case.sealed_dataset_id})
    db.commit()
    return blind.case_dict(db, case, detailed=True)


@router.get('/{case_id}')
def detail(case_id: int, db=Depends(get_db), u=Depends(current_user)):
    return blind.case_dict(db, _case(db, case_id), detailed=True)


@router.post('/{case_id}/candidates', status_code=201)
def add_candidate(case_id: int, data: CandidateInput, db=Depends(get_db), u=Depends(can_write)):
    case = _case(db, case_id)
    job = blind.create_candidate(db, case, data, u)
    record(db, u.email, 'blind.candidate.create', {'case': case.id, 'id': job.id, 'params': job.params})
    db.commit()
    job_service.enqueue(job.id)
    return job_dict(job)


@router.post('/{case_id}/select')
def select_candidate(case_id: int, data: SelectInput, db=Depends(get_db), u=Depends(admin_only)):
    case = _case(db, case_id)
    case, unseal = blind.select_candidate(db, case, data.job_id, u)
    record(db, u.email, 'blind.case.select', {'case': case.id, 'job': data.job_id, 'threshold': case.locked_threshold, 'unseal': unseal.id})
    db.commit()
    job_service.enqueue(unseal.id)
    return blind.case_dict(db, case, detailed=True)


@router.post('/{case_id}/retry')
def retry_unseal(case_id: int, db=Depends(get_db), u=Depends(admin_only)):
    case = _case(db, case_id)
    case, job = blind.retry_unseal(db, case, u)
    record(db, u.email, 'blind.case.retry', {'case': case.id, 'job': job.id, 'attempt': job.attempts})
    db.commit()
    job_service.enqueue(job.id)
    return blind.case_dict(db, case, detailed=True)


@router.post('/{case_id}/approve')
def approve(case_id: int, db=Depends(get_db), u=Depends(admin_only)):
    case = _case(db, case_id)
    job = blind.approve_case(db, case, u)
    record(db, u.email, 'blind.case.approve', {'case': case.id, 'job': job.id})
    db.commit()
    return job_dict(job)


@router.get('/{case_id}/unseal-result')
def unseal_result(case_id: int, db=Depends(get_db), u=Depends(current_user)):
    case = _case(db, case_id)
    if case.status != 'completed':
        raise HTTPException(409, '开封结果尚未完整落定，暂不可读取')
    job = db.get(Job, case.unseal_job_id) if case.unseal_job_id else None
    if not job or job.status != 'completed' or not job.result:
        raise HTTPException(409, '开封结果尚未完整落定，暂不可读取')
    return job_dict(job)

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import BlindCase, Dataset, Job
from src.schemas.job import JobInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import jobs
from src.services.audit import record
from src.utils.serialization import job_dict
router=APIRouter(prefix='/jobs')


@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    result=[]
    for job in db.scalars(select(Job).order_by(Job.id.desc()).limit(100)):
        if job.scope=='unseal':
            case=db.get(BlindCase,job.case_id) if job.case_id else None
            if not case or case.status!='completed':
                continue  # sealed results appear only after the case fully settles
        elif job.scope=='standard':
            d=db.get(Dataset,job.dataset_id) if job.dataset_id else None
            if d and d.kind!='standard':
                continue  # never expose blind development/sealed batches via the generic entry
        result.append(job_dict(job))
    return result


@router.post('',status_code=201)
def create(data:JobInput,db=Depends(get_db),u=Depends(can_write)):
    j=jobs.create(db,data,u); record(db,u.email,'job.create',{'id':j.id,'params':j.params})
    db.commit(); jobs.enqueue(j.id); return job_dict(j)


@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    if j.scope=='unseal':
        case=db.get(BlindCase,j.case_id) if j.case_id else None
        if not case or case.status!='completed':
            raise HTTPException(403,'封存集结果尚未完整落定，不能读取')
    if j.scope=='standard':
        d=db.get(Dataset,j.dataset_id) if j.dataset_id else None
        if d and d.kind!='standard': raise HTTPException(403,'该任务绑定的批次不属于普通分析入口')
    return job_dict(j)


@router.post('/{id}/approve')
def approve(id:int,db=Depends(get_db),u=Depends(admin_only)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    if j.scope=='unseal': raise HTTPException(409,'封存集结果须通过盲评案件批准')
    if j.scope!='standard': raise HTTPException(409,'候选试验不单独批准，请先选定并完成盲评开封')
    if j.status!='completed':raise HTTPException(409,'仅已完成结果可以批准')
    j.approved=True; record(db,u.email,'job.approve',{'id':id}); db.commit()
    return job_dict(j)

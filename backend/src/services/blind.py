import time
from fastapi import HTTPException
from sqlalchemy import select, update
from src.models import BlindCase, Dataset, Job, User
from src.services.business import apply_artifact, split_blind
from src.services.datasets import validate_records
from src.services.jobs import normalized_params


def used_reader_ids(db):
    """Readers already used by any blind case, so a label shown once cannot later be sealed."""
    ids = set()
    for case in db.scalars(select(BlindCase)):
        split = case.split or {}
        ids.update(str(v) for v in split.get('sealed_readers', []))
        ids.update(str(v) for v in split.get('development_readers', []))
    return ids


def _dataset(db, name, source, records, kind):
    from src.utils.serialization import checksum
    d = Dataset(name=name, source=source, records=records, checksum=checksum(records), kind=kind, case_id=None, created_at=time.time())
    db.add(d)
    db.flush()
    return d


def create_case(db, data, user):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '案件名称去除空格后至少需要两个字符')
    if db.scalar(select(BlindCase).where(BlindCase.name == name)):
        raise HTTPException(409, '该盲评案件名已存在，请修改名称')
    rows = validate_records([dict(r) for r in data.records])
    reader_ids = [str(r.get('reader_id')) for r in rows]
    if any(not v or v == 'None' for v in reader_ids):
        raise HTTPException(422, '盲评批次每条记录都需要匿名读者编号')
    if len(set(reader_ids)) != len(reader_ids):
        raise HTTPException(422, '盲评批次内读者编号必须唯一，否则无法按读者固定分组')
    duplicated = sorted(set(reader_ids) & used_reader_ids(db))
    if duplicated:
        raise HTTPException(409, f'读者 {duplicated[0]} 已在其他盲评案中出现，不能重复使用同一读者的标签')
    try:
        development, sealed, split = split_blind(rows)
    except ValueError as exc:
        raise HTTPException(422, f'无法固定盲评分组：{exc}') from exc
    case = BlindCase(
        name=name, source=data.source, split=split, status='developing',
        created_by=user.id, created_at=time.time(),
    )
    db.add(case)
    db.flush()
    blind_ds = _dataset(db, f'{name} · 盲评全量批次', data.source, rows, 'blind')
    dev_ds = _dataset(db, f'{name} · 开发集', data.source, development, 'development')
    sealed_ds = _dataset(db, f'{name} · 封存集', data.source, sealed, 'sealed')
    case.blind_dataset_id = blind_ds.id
    case.development_dataset_id = dev_ds.id
    case.sealed_dataset_id = sealed_ds.id
    blind_ds.case_id = dev_ds.case_id = sealed_ds.case_id = case.id
    db.flush()
    return case


def get_case(db, case_id):
    case = db.get(BlindCase, case_id)
    if not case:
        raise HTTPException(404, '盲评案件不存在')
    return case


def _candidate(db, case):
    if case.status != 'developing':
        raise HTTPException(409, '只有开发中的案件可以新增候选试验')
    development = db.get(Dataset, case.development_dataset_id)
    if not development:
        raise HTTPException(409, '开发集缺失，无法创建候选试验')
    return development


def create_candidate(db, case, data, user):
    development = _candidate(db, case)
    params = normalized_params(data.params)
    job = Job(
        name=data.name, dataset_id=development.id, params=params, status='queued',
        scope='development', case_id=case.id, created_by=user.id, created_at=time.time(),
    )
    db.add(job)
    db.flush()
    return job


def list_candidates(db, case):
    return list(db.scalars(select(Job).where(Job.case_id == case.id, Job.scope == 'development').order_by(Job.id)))


def select_candidate(db, case, job_id, user):
    if case.status != 'developing':
        raise HTTPException(409, '该案已锁定，一案只接纳一次选择；请查看先落定的候选')
    job = db.get(Job, job_id)
    if not job or job.scope != 'development' or job.case_id != case.id:
        raise HTTPException(404, '候选试验不存在或不属于本案')
    if job.status != 'completed' or not job.artifact:
        raise HTTPException(409, '只有已完成并保留训练成果的候选才能被选定')
    threshold = float(job.params.get('threshold', 0.5))
    now = time.time()
    # Conditional update: concurrent selections race here and only the first row wins.
    won = db.execute(
        update(BlindCase)
        .where(BlindCase.id == case.id, BlindCase.status == 'developing')
        .values(status='locked', chosen_job_id=job.id, locked_artifact=job.artifact,
                locked_threshold=threshold, locked_at=now, error='')
    ).rowcount == 1
    if not won:
        db.rollback()
        latest = db.get(BlindCase, case.id)
        raise HTTPException(409, f'该案已由先落定者选定（候选 #{latest.chosen_job_id if latest else "未知"}），一案只接纳一次选择')
    sealed = db.get(Dataset, case.sealed_dataset_id)
    if not sealed:
        raise HTTPException(409, '封存集缺失，无法安排开封')
    unseal = Job(
        name=f'{case.name} · 封存集一次性开封',
        dataset_id=sealed.id, params={'threshold': threshold, 'regularization': float(job.params.get('regularization', 1.0))},
        status='queued', scope='unseal', case_id=case.id, attempts=1,
        created_by=user.id, created_at=now,
    )
    db.add(unseal)
    db.flush()
    case.unseal_job_id = unseal.id
    db.flush()
    return case, unseal


def retry_unseal(db, case, user):
    if case.status not in ('locked', 'unsealing'):
        raise HTTPException(409, '该案尚未锁定或开封已完整落定，无需恢复')
    job = db.get(Job, case.unseal_job_id) if case.unseal_job_id else None
    if not job:
        raise HTTPException(409, '开封任务缺失，无法恢复')
    if job.status == 'completed':
        raise HTTPException(409, '开封结果已落定，不能重复评估')
    if job.status == 'running':
        raise HTTPException(409, '开封正在进行，请稍后查看')
    job.status = 'queued'
    job.error = ''
    job.attempts = (job.attempts or 1) + 1
    case.status = 'unsealing'
    case.error = ''
    db.flush()
    return case, job


def approve_case(db, case, user):
    if case.status != 'completed':
        raise HTTPException(409, '开封结果尚未完整落定，不能批准或用于简报')
    job = db.get(Job, case.unseal_job_id) if case.unseal_job_id else None
    if not job or job.status != 'completed' or not job.result:
        raise HTTPException(409, '开封结果尚未完整落定，不能批准或用于简报')
    if job.approved:
        return job
    job.approved = True
    db.flush()
    return job


def case_dict(db, case, detailed=False):
    split = case.split or {}
    data = {
        'id': case.id, 'name': case.name, 'source': case.source, 'status': case.status,
        'blind_dataset_id': case.blind_dataset_id, 'development_dataset_id': case.development_dataset_id,
        'sealed_dataset_id': case.sealed_dataset_id, 'chosen_job_id': case.chosen_job_id,
        'unseal_job_id': case.unseal_job_id, 'locked_threshold': case.locked_threshold,
        'error': case.error, 'created_at': case.created_at, 'locked_at': case.locked_at,
        'completed_at': case.completed_at, 'created_by': case.created_by,
        'split': {'seed': split.get('seed'), 'sealed_ratio': split.get('sealed_ratio'),
                  'development_count': len(split.get('development_readers', [])),
                  'sealed_count': len(split.get('sealed_readers', []))},
    }
    if detailed:
        creator = db.get(User, case.created_by)
        data['created_by_name'] = creator.name if creator else ''
        data['candidates'] = [job_dict(db, j) for j in list_candidates(db, case)]
        job = db.get(Job, case.unseal_job_id) if case.unseal_job_id else None
        if job:
            unseal = job_dict(db, job)
            if case.status != 'completed':
                # Sealed outcomes stay closed until the whole case is settled.
                unseal['result'] = {}
                unseal['sealed'] = True
            data['unseal'] = unseal
        else:
            data['unseal'] = None
        if case.status == 'completed':
            data['sealed_readers'] = list(split.get('sealed_readers', []))
    return data


def job_dict(db, job):
    data = {k: getattr(job, k) for k in ['id', 'name', 'dataset_id', 'params', 'status', 'result', 'error', 'approved', 'created_at', 'finished_at', 'scope', 'case_id', 'attempts']}
    if job.scope == 'development' and job.status == 'completed':
        data['artifact_locked'] = bool(job.artifact)
        data['artifact_summary'] = {k: job.artifact.get(k) for k in ['train_size', 'valid_size', 'random_state']} if job.artifact else {}
    return data

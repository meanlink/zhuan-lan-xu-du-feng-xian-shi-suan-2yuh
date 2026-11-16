import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import BlindCase, Job, Dataset, Report
from src.services.business import apply_artifact, fit_artifact
from src.services.reports import deliver
from src.services.audit import record
logging.basicConfig(level=logging.INFO)


def _complete(db, job, result, artifact=None):
    json.dumps(result, allow_nan=False)
    job.result = result
    if artifact is not None:
        job.artifact = artifact
    job.status = 'completed'
    job.error = ''
    job.finished_at = time.time()
    record(db, 'worker', 'job.completed', {'id': job.id, 'scope': job.scope})
    if job.scope == 'unseal':
        case = db.get(BlindCase, job.case_id)
        if case:
            case.status = 'completed'
            case.completed_at = job.finished_at
            case.error = ''
            record(db, 'worker', 'blind.case.completed', {'id': case.id, 'job': job.id})


def _fail(db, job, error):
    job.status = 'failed'
    job.error = str(error)[:990]
    job.finished_at = time.time()
    record(db, 'worker', 'job.failed', {'id': job.id, 'scope': job.scope, 'error': job.error})
    if job.scope == 'unseal':
        case = db.get(BlindCase, job.case_id)
        if case:
            case.status = 'unsealing'
            case.error = job.error


def execute(job_id):
    with Session() as db:
        j = db.get(Job, job_id)
        if not j or j.status != 'queued':
            return
        j.status = 'running'
        db.commit()
        try:
            dataset = db.get(Dataset, j.dataset_id)
            if not dataset:
                raise ValueError('绑定批次不存在')
            if j.scope == 'standard':
                if dataset.kind != 'standard':
                    raise ValueError('盲评批次与封存集不能经普通分析入口计算')
                result, artifact = fit_artifact(dataset.records, j.params)
                _complete(db, j, result, artifact)
            elif j.scope == 'development':
                case = db.get(BlindCase, j.case_id)
                if not case:
                    raise ValueError('所属盲评案件不存在')
                if dataset.kind != 'development' or dataset.case_id != case.id:
                    raise ValueError('候选试验只能使用本案开发集')
                # A candidate queued before selection still settles on the development
                # set only; it can no longer be chosen, and sealed labels are untouched.
                result, artifact = fit_artifact(dataset.records, j.params)
                _complete(db, j, result, artifact)
            elif j.scope == 'unseal':
                case = db.get(BlindCase, j.case_id)
                if not case or case.status not in ('locked', 'unsealing'):
                    raise ValueError('案件不在可开封状态')
                if not case.locked_artifact:
                    raise ValueError('缺少锁定的训练成果，无法开封')
                if dataset.kind != 'sealed' or dataset.case_id != case.id:
                    raise ValueError('开封只能使用本案固定的封存集')
                case.status = 'unsealing'
                db.commit()
                result = apply_artifact(dataset.records, case.locked_artifact)
                _complete(db, j, result)
            else:
                raise ValueError('未知的分析范围')
        except Exception as e:
            logging.exception('Analysis failed')
            _fail(db, j, e)
        db.commit()


def tick():
    with Session() as db:
        queued = list(db.scalars(select(Job.id).where(Job.status == 'queued').limit(3)))
    for job_id in queued:
        execute(job_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled == True, Report.next_run <= time.time())):
            d = deliver(db, r)
            if d:
                record(db, 'worker', 'report.delivered', {'id': r.id, 'delivery': d.id})
        db.commit()


def main():
    r = Redis.from_url(REDIS_URL, socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    # Unseal jobs are re-queued under their case status so retries reuse the lock.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status == 'running')):
            j.status = 'queued'
            record(db, 'worker', 'job.recovered', {'id': j.id, 'scope': j.scope})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item = r.blpop('analysis:queue', timeout=1)
            if item:
                execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry')
            time.sleep(2)


if __name__ == '__main__':
    main()

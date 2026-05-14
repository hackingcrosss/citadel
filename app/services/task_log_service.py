import json
import time
import calendar

TASK_LOG_KEY = 'citadel:task_log'
MAX_TASKS = 100


def _redis():
    import redis
    from flask import current_app
    url = current_app.config.get(
        'REDIS_URL',
        current_app.config.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
    )
    return redis.from_url(url, decode_responses=True)


def log_task(task_id, task_type, description, meta=None):
    """Record a submitted task so it shows up in the task log."""
    r = _redis()
    entry = {
        'task_id': task_id,
        'type': task_type,
        'description': description,
        'submitted_at': time.time(),
    }
    if meta:
        entry['meta'] = meta
    r.lpush(TASK_LOG_KEY, json.dumps(entry))
    r.ltrim(TASK_LOG_KEY, 0, MAX_TASKS - 1)


def get_tasks():
    """Return all logged tasks enriched with current Celery status."""
    from app.tasks.celery_app import celery

    r = _redis()
    raw = r.lrange(TASK_LOG_KEY, 0, -1)
    now = time.time()
    result = []

    for item in raw:
        t = json.loads(item)
        task_id = t['task_id']
        ar = celery.AsyncResult(task_id)
        status = ar.status

        entry = {
            'task_id': task_id,
            'type': t.get('type'),
            'description': t.get('description'),
            'submitted_at': t.get('submitted_at', now),
            'status': status,
            'meta': t.get('meta', {}),
        }

        submitted_at = t.get('submitted_at', now)

        if status in ('SUCCESS', 'FAILURE'):
            date_done = ar.date_done
            if date_done:
                done_ts = calendar.timegm(date_done.timetuple())
                entry['completed_at'] = done_ts
                entry['duration_s'] = round(done_ts - submitted_at, 1)
            if status == 'FAILURE':
                try:
                    entry['error'] = str(ar.result)
                except Exception:
                    entry['error'] = 'Unknown error'
        else:
            entry['elapsed_s'] = round(now - submitted_at, 1)

        result.append(entry)

    return result


def clear_completed():
    """Remove SUCCESS / FAILURE / REVOKED tasks from the log."""
    from app.tasks.celery_app import celery

    r = _redis()
    raw = r.lrange(TASK_LOG_KEY, 0, -1)
    keep = []
    for item in raw:
        t = json.loads(item)
        ar = celery.AsyncResult(t['task_id'])
        if ar.status not in ('SUCCESS', 'FAILURE', 'REVOKED'):
            keep.append(item)

    r.delete(TASK_LOG_KEY)
    for item in reversed(keep):
        r.lpush(TASK_LOG_KEY, item)
    if keep:
        r.ltrim(TASK_LOG_KEY, 0, MAX_TASKS - 1)

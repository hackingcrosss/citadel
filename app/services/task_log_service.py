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


def log_task(task_id, task_type, description, meta=None, user_id=None):
    """Record a submitted task so it shows up in the task log.

    *user_id* tags the entry so get_tasks / clear_completed can scope by
    ownership (API-IDOR-01).
    """
    r = _redis()
    entry = {
        'task_id': task_id,
        'type': task_type,
        'description': description,
        'submitted_at': time.time(),
    }
    if meta:
        entry['meta'] = meta
    if user_id is not None:
        entry['user_id'] = user_id
    r.lpush(TASK_LOG_KEY, json.dumps(entry))
    r.ltrim(TASK_LOG_KEY, 0, MAX_TASKS - 1)


def get_tasks(user=None):
    """Return logged tasks enriched with current Celery status.

    If *user* is provided and is not admin/auditor, only tasks owned by
    that user are returned (API-IDOR-01).  Legacy entries without a
    user_id are visible only to admins/auditors.
    """
    from app.tasks.celery_app import celery

    r = _redis()
    raw = r.lrange(TASK_LOG_KEY, 0, -1)
    now = time.time()
    result = []

    # Determine whether we need to filter
    scope_all = user is None or getattr(user, 'is_admin', False) or getattr(user, 'is_auditor', False)

    for item in raw:
        t = json.loads(item)

        # Ownership filter (API-IDOR-01)
        if not scope_all:
            if t.get('user_id') != getattr(user, 'id', None):
                continue

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


def get_task_owner(task_id):
    """Return the user_id that submitted *task_id*, or None."""
    r = _redis()
    raw = r.lrange(TASK_LOG_KEY, 0, -1)
    for item in raw:
        t = json.loads(item)
        if t['task_id'] == task_id:
            return t.get('user_id')
    return None


def clear_completed(user=None):
    """Remove SUCCESS / FAILURE / REVOKED tasks from the log.

    If *user* is provided and is not admin, only that user's completed
    tasks are removed (API-IDOR-01).
    """
    from app.tasks.celery_app import celery

    scope_all = user is None or getattr(user, 'is_admin', False)

    r = _redis()
    raw = r.lrange(TASK_LOG_KEY, 0, -1)
    keep = []
    for item in raw:
        t = json.loads(item)
        ar = celery.AsyncResult(t['task_id'])
        is_done = ar.status in ('SUCCESS', 'FAILURE', 'REVOKED')
        # Keep the entry if it's not done, or if it belongs to someone
        # else and we're scoping by user.
        if not is_done:
            keep.append(item)
        elif not scope_all and t.get('user_id') != getattr(user, 'id', None):
            keep.append(item)

    r.delete(TASK_LOG_KEY)
    for item in reversed(keep):
        r.lpush(TASK_LOG_KEY, item)
    if keep:
        r.ltrim(TASK_LOG_KEY, 0, MAX_TASKS - 1)

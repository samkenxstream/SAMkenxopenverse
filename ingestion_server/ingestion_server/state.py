import shelve
import datetime
import enum
import logging as log
from filelock import FileLock
"""
Indexing is distributed across multiple independent hosts. We don't want to 
"go live" in production with the newly indexed data until all of the indexing 
workers have finished their tasks. To that end, we need to track the state of 
each worker, and be notified when the job has finished.

State is persisted to the disk using shelve. Concurrent writes aren't allowed,
so all operations need a lock.
"""


class WorkerStatus(enum.Enum):
    RUNNING = 0
    FINISHED = 1


def register_indexing_job(worker_ips, target_index):
    """
    Track the hosts that are running indexing jobs. Only one indexing job can
    run at a time.

    :param worker_ips:
    :param target_index: The
    :return: Return True if scheduling succeeds
    """
    with FileLock('lock'), shelve.open('db', writeback=True) as db:
        # Wipe last job out if it has finished.
        indexing_in_progress = False
        if 'worker_statuses' in db:
            for worker in db['worker_statuses']:
                if db['worker_statuses'][worker] == WorkerStatus.RUNNING:
                    indexing_in_progress = True
        if indexing_in_progress:
            log.error(
                'Failed to schedule indexing job; another one is running.'
            )
            return False

        # Register the workers.
        worker_statuses = {}
        for worker_url in worker_ips:
            worker_statuses[worker_url] = WorkerStatus.RUNNING
        db['worker_statuses'] = worker_statuses
        db['start_time'] = datetime.datetime.now()
        db['target_index'] = target_index
        return True


def worker_finished(worker_ip):
    """
    The scheduler received a notification indicating an indexing worker has
    finished its task.
    :param worker_ip: The private IP of the worker.
    :return: True if all workers have finished indexing else False
    """
    with FileLock('lock'), shelve.open('db', writeback=True) as db:
        try:
            db['worker_statuses'][worker_ip] = WorkerStatus.FINISHED
        except KeyError:
            log.error(
                'An indexer worker notified us it finished its task, but '
                'we are not tracking it.'
            )
        for worker_key in db['worker_statuses']:
            if db['worker_statuses'][worker_key] == WorkerStatus.RUNNING:
                return False
        return db['target_index']


def clear_state():
    """
    Forget about all running index jobs. Use with care.
    """
    with FileLock('lock'), shelve.open('db', writeback=True) as db:
        for key in db:
            del db[key]
    log.info('Cleared indexing state.')

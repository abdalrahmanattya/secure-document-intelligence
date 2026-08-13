import time

from .main import process_job, queue, store
from .queue import DynamoJobQueue

if not isinstance(queue, DynamoJobQueue):
    raise RuntimeError("worker service requires QUEUE_BACKEND=dynamodb")

while True:
    job = queue.claim()
    if job:
        try:
            process_job(job)
            if store.get(job.document_id, job.tenant_id).state == "FAILED": raise RuntimeError("document processing failed")
            queue.finish(job)
        except Exception as error: queue.finish(job, str(error))
    else:
        time.sleep(1)

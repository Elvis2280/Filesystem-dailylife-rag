"""Persistent FIFO for chat turns, with one active turn owned by the dispatcher."""

import json
from dataclasses import dataclass
from hashlib import sha256
from time import time
from typing import Any, Literal
from uuid import UUID

from redis.asyncio import Redis

from app.core.config import settings

JobStatus = Literal["queued", "running", "completed", "failed"]
MAX_PENDING_JOBS = 64
RESULT_TTL_SECONDS = 24 * 60 * 60
_PREFIX = "rag:chat:job:"
_PENDING = "rag:chat:pending"
_ACTIVE = "rag:chat:active"

# Each operation changes the queue and the visible job state in one Redis write.
_SUBMIT = """
if redis.call('EXISTS', KEYS[1]) == 1 then
    if redis.call('HGET', KEYS[1], 'fingerprint') ~= ARGV[1] then
        return 'conflict'
    end
    return 'existing'
end
if redis.call('LLEN', KEYS[2]) >= tonumber(ARGV[2]) then
    return 'full'
end
redis.call('HSET', KEYS[1], 'fingerprint', ARGV[1],
    'workspace_id', ARGV[3], 'message', ARGV[4],
    'queued_at', ARGV[5], 'status', 'queued')
redis.call('RPUSH', KEYS[2], ARGV[6])
return 'created'
"""

_CLAIM = """
if redis.call('EXISTS', KEYS[2]) == 1 then
    return false
end
local id = redis.call('LPOP', KEYS[1])
if not id then
    return false
end
redis.call('SET', KEYS[2], id)
redis.call('HSET', ARGV[1] .. id, 'status', 'running')
return id
"""

_RECOVER = """
local id = redis.call('GET', KEYS[2])
if id then
    redis.call('HSET', ARGV[1] .. id, 'status', 'queued')
    redis.call('LPUSH', KEYS[1], id)
    redis.call('DEL', KEYS[2])
end
"""

_FINISH = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
redis.call('HSET', KEYS[2], 'status', ARGV[2], ARGV[3], ARGV[4])
redis.call('HDEL', KEYS[2], 'message')
redis.call('EXPIRE', KEYS[2], ARGV[5])
redis.call('DEL', KEYS[1])
return 1
"""


class ChatJobConflict(Exception):
    """The caller reused a submission key for a different question."""


class ChatQueueFull(Exception):
    """The pending queue is at its capacity."""


@dataclass(frozen=True, slots=True)
class ChatJob:
    id: UUID
    workspace_id: UUID
    status: JobStatus
    queued_at: float
    message: str | None = None
    answer: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


def receipt_job_id(receipt: UUID) -> UUID:
    """Use an opaque receipt to prove access even with a shared API key."""
    return UUID(bytes=sha256(receipt.bytes).digest()[:16])


class ChatJobs:
    def __init__(self) -> None:
        self.redis = Redis(
            host=settings.CHAT_REDIS_HOST,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )

    async def submit(self, workspace_id: UUID, message: str, receipt: UUID) -> UUID:
        job_id = receipt_job_id(receipt)
        fingerprint = sha256(workspace_id.bytes + message.encode()).hexdigest()
        result = await self.redis.eval(
            _SUBMIT,
            2,
            _PREFIX + str(job_id),
            _PENDING,
            fingerprint,
            MAX_PENDING_JOBS,
            str(workspace_id),
            message,
            time(),
            str(job_id),
        )
        if result == "conflict":
            raise ChatJobConflict
        if result == "full":
            raise ChatQueueFull
        return job_id

    async def get(self, job_id: UUID) -> ChatJob | None:
        record = await self.redis.hgetall(_PREFIX + str(job_id))
        if not record:
            return None
        return ChatJob(
            id=job_id,
            workspace_id=UUID(record["workspace_id"]),
            status=record["status"],
            queued_at=float(record["queued_at"]),
            message=record.get("message"),
            answer=json.loads(record["answer"]) if "answer" in record else None,
            error=json.loads(record["error"]) if "error" in record else None,
        )

    async def claim(self) -> ChatJob | None:
        job_id = await self.redis.eval(_CLAIM, 2, _PENDING, _ACTIVE, _PREFIX)
        return await self.get(UUID(job_id)) if job_id else None

    async def recover(self) -> None:
        await self.redis.eval(_RECOVER, 2, _PENDING, _ACTIVE, _PREFIX)

    async def finish(
        self,
        job_id: UUID,
        *,
        answer: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        await self.redis.eval(
            _FINISH,
            2,
            _ACTIVE,
            _PREFIX + str(job_id),
            str(job_id),
            "completed" if error is None else "failed",
            "answer" if error is None else "error",
            json.dumps(answer if error is None else error),
            RESULT_TTL_SECONDS,
        )


chat_jobs = ChatJobs()

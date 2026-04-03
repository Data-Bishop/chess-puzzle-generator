"""Redis queue management for job processing."""
import json
import logging
import redis
from typing import Optional, Dict, Any
from config import settings

logger = logging.getLogger(__name__)


class RedisQueue:
    """Redis-based job queue."""

    def __init__(self):
        """Initialize Redis connection."""
        self.redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True
        )
        self.queue_name = "job_queue"

    def push(self, job_id: str, job_data: Dict[str, Any]) -> bool:
        """
        Push a job to the queue.

        Args:
            job_id: UUID of the job
            job_data: Job data to store (will be JSON serialized)

        Returns:
            bool: True if successful
        """
        try:
            # Add job ID to queue (FIFO using RPUSH/LPOP)
            self.redis_client.rpush(self.queue_name, job_id)

            # Store job data separately with job ID as key
            self.redis_client.setex(
                f"job:{job_id}",
                3600,  # 1 hour TTL
                json.dumps(job_data)
            )
            return True
        except Exception as e:
            logger.error("Error pushing job to queue: %s", e)
            return False

    def pop(self, timeout: int = 0) -> Optional[tuple[str, Dict[str, Any]]]:
        """
        Pop a job from the queue (blocking).

        Args:
            timeout: Seconds to wait for a job (0 = block indefinitely)

        Returns:
            Tuple of (job_id, job_data) or None if timeout
        """
        import time as time_module

        try:
            # BLPOP returns (queue_name, job_id) or None
            result = self.redis_client.blpop(self.queue_name, timeout=timeout)

            if not result:
                return None

            _, job_id = result

            # Retrieve job data with retry (handles race condition)
            job_data_json = None
            for attempt in range(3):
                job_data_json = self.redis_client.get(f"job:{job_id}")
                if job_data_json:
                    break
                logger.warning("Retry %d: job data not found for job %s, waiting...", attempt + 1, job_id)
                time_module.sleep(0.5)

            if not job_data_json:
                logger.warning("Job data not found for job %s after retries", job_id)
                return None

            job_data = json.loads(job_data_json)
            return (job_id, job_data)

        except Exception as e:
            logger.error("Error popping job from queue: %s", e)
            return None

    def get_queue_length(self) -> int:
        """
        Get the number of jobs in the queue.

        Returns:
            int: Number of pending jobs
        """
        try:
            return self.redis_client.llen(self.queue_name)
        except Exception as e:
            logger.error("Error getting queue length: %s", e)
            return 0

    def clear_queue(self) -> bool:
        """
        Clear all jobs from the queue (for testing/debugging).

        Returns:
            bool: True if successful
        """
        try:
            self.redis_client.delete(self.queue_name)
            return True
        except Exception as e:
            logger.error("Error clearing queue: %s", e)
            return False

    def health_check(self) -> bool:
        """
        Check if Redis is accessible.

        Returns:
            bool: True if Redis is healthy
        """
        try:
            self.redis_client.ping()
            return True
        except Exception as e:
            logger.error("Redis health check failed: %s", e)
            return False


# Global queue instance
queue = RedisQueue()

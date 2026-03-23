"""
step1/sqs_client.py — SQS Publisher Wrapper

HOW IT WORKS:
─────────────
Publishes messages to an AWS SQS queue.
Step 2 (Worker) consumes these messages.

The message contains the normalized SQSMessage:
    {event_id, repo, workflow_run_id, run_url, timestamp}

WHY A WRAPPER:
    - Testability: mock SQSClient in tests without AWS
    - Error handling: retry and logging in one place
    - Abstraction: swap SQS for another queue if needed

QUEUE NAME:
    Set via environment variable SQS_QUEUE_URL.
    In SAM template, this is created automatically.

COMMUNICATION:
─────────────
webhook_handler.py → SQSClient.publish(message) → SQS Queue → Step 2 Worker
"""

import json
from typing import Dict, Any, Optional, Protocol

import boto3
from botocore.exceptions import ClientError

from shared.config import settings
from shared.logger import get_logger

logger = get_logger("step1.sqs_client")


class QueuePublisher(Protocol):
    """Interface for queue publishers (for mocking in tests)."""
    def publish(self, message: Dict[str, Any]) -> bool: ...


class SQSClient:
    """
    Publishes messages to AWS SQS.

    In production, the queue URL is injected via env var
    (set by SAM template).
    """

    def __init__(self, queue_url: Optional[str] = None):
        import os
        self._queue_url = queue_url or os.getenv("SQS_QUEUE_URL", "")
        self._client = boto3.client("sqs", region_name=settings.AWS_REGION)

    def publish(self, message: Dict[str, Any]) -> bool:
        """
        Send a message to the SQS queue.

        Args:
            message: Dict to serialize as JSON and send.
                    Expected: SQSMessage.model_dump()

        Returns:
            True if sent successfully, False otherwise
        """
        if not self._queue_url:
            logger.error("sqs_queue_url_not_set")
            return False

        try:
            response = self._client.send_message(
                QueueUrl=self._queue_url,
                MessageBody=json.dumps(message),
                MessageAttributes={
                    "EventSource": {
                        "DataType": "String",
                        "StringValue": "repomind-webhook",
                    }
                },
            )
            message_id = response.get("MessageId", "unknown")
            logger.info(
                "sqs_message_sent",
                message_id=message_id,
                event_id=message.get("event_id"),
            )
            return True

        except ClientError as e:
            logger.error(
                "sqs_publish_failed",
                error=str(e),
                event_id=message.get("event_id"),
            )
            return False


class LocalQueueClient:
    """
    Development-mode queue that logs messages instead of sending to SQS.
    Stores messages in memory for testing.
    """

    def __init__(self):
        self.messages = []

    def publish(self, message: Dict[str, Any]) -> bool:
        self.messages.append(message)
        logger.info(
            "local_queue_message",
            event_id=message.get("event_id"),
            total_messages=len(self.messages),
        )
        return True


def get_queue_client() -> QueuePublisher:
    """Factory: returns SQSClient in production, LocalQueueClient in dev."""
    if settings.ENVIRONMENT == "development":
        return LocalQueueClient()
    return SQSClient()

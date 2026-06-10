import json
import os
import uuid
import boto3
from datetime import datetime, timezone
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")
table = dynamodb.Table(os.environ["SUBSCRIPTIONS_TABLE"])
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _get_subscribers(topic: str) -> list[str]:
    result = table.query(
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": f"TOPIC#{topic}"},
    )
    return [item["user_id"] for item in result.get("Items", [])]


@logger.inject_lambda_context(correlation_id_path="requestContext.requestId")
def handler(event: dict, context: LambdaContext) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
        topic = body.get("topic", "").strip()
        message = body.get("message", "").strip()
        metadata = body.get("metadata", {})

        if not topic or not message:
            return _response(400, {"error": "topic and message are required"})

        subscribers = _get_subscribers(topic)
        if not subscribers:
            return _response(200, {"message": "no subscribers", "topic": topic})

        notification_id = str(uuid.uuid4())
        payload = {
            "notification_id": notification_id,
            "topic": topic,
            "message": message,
            "metadata": metadata,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "subscribers": subscribers,
        }

        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=json.dumps(payload),
            MessageAttributes={
                "topic": {"DataType": "String", "StringValue": topic}
            },
        )

        logger.info("Notification published", extra={"notification_id": notification_id, "subscriber_count": len(subscribers)})
        return _response(202, {
            "notification_id": notification_id,
            "queued_for": len(subscribers),
        })

    except Exception as exc:
        logger.exception("Publish failed")
        return _response(500, {"error": str(exc)})

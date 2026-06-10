import json
import os
import boto3
from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
dynamodb = boto3.resource("dynamodb")
connections_table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])
processor = BatchProcessor(event_type=EventType.SQS)

APIGW_ENDPOINT = os.environ["APIGW_ENDPOINT"]
apigw = boto3.client("apigatewaymanagementapi", endpoint_url=APIGW_ENDPOINT)


def _get_connections(user_id: str) -> list[str]:
    result = connections_table.query(
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": f"USER#{user_id}"},
    )
    return [item["connection_id"] for item in result.get("Items", [])]


def _push(connection_id: str, payload: dict) -> bool:
    try:
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(payload).encode(),
        )
        return True
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("GoneException", "ForbiddenException"):
            logger.warning("Stale connection, removing", extra={"connection_id": connection_id})
            connections_table.delete_item(
                Key={"pk": f"USER#{connection_id.split('#')[0]}", "sk": connection_id}
            )
        else:
            raise
    return False


def record_handler(record):
    sns_envelope = json.loads(record.body)
    payload = json.loads(sns_envelope["Message"])

    notification_out = {
        "notification_id": payload["notification_id"],
        "topic": payload["topic"],
        "message": payload["message"],
        "metadata": payload.get("metadata", {}),
        "published_at": payload["published_at"],
    }

    delivered = 0
    for user_id in payload.get("subscribers", []):
        connections = _get_connections(user_id)
        for conn_id in connections:
            if _push(conn_id, notification_out):
                delivered += 1

    logger.info("Delivery complete", extra={
        "notification_id": payload["notification_id"],
        "delivered": delivered,
        "subscribers": len(payload.get("subscribers", [])),
    })


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext):
    return process_partial_response(
        event=event,
        record_handler=record_handler,
        processor=processor,
        context=context,
    )

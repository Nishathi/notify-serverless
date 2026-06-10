import json
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_TABLE", "test-subs")
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:ap-south-1:123456789:test")
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")


@patch("boto3.client")
@patch("boto3.resource")
def test_publish_success(mock_resource, mock_client):
    table = MagicMock()
    table.query.return_value = {"Items": [{"user_id": "u1"}, {"user_id": "u2"}]}
    mock_resource.return_value.Table.return_value = table
    sns_client = MagicMock()
    mock_client.return_value = sns_client

    from lambdas.publish.handler import handler

    event = {
        "body": json.dumps({"topic": "orders", "message": "Ship arrived"}),
        "requestContext": {"requestId": "req-1"},
    }
    resp = handler(event, MagicMock())
    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body["queued_for"] == 2
    sns_client.publish.assert_called_once()


@patch("boto3.client")
@patch("boto3.resource")
def test_publish_no_subscribers(mock_resource, mock_client):
    table = MagicMock()
    table.query.return_value = {"Items": []}
    mock_resource.return_value.Table.return_value = table

    from lambdas.publish.handler import handler

    event = {
        "body": json.dumps({"topic": "empty-topic", "message": "hello"}),
        "requestContext": {"requestId": "req-2"},
    }
    resp = handler(event, MagicMock())
    assert resp["statusCode"] == 200
    assert "no subscribers" in json.loads(resp["body"])["message"]

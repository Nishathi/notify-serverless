import json
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_TABLE", "test-subs")
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")


@patch("boto3.resource")
def test_subscribe_success(mock_resource):
    table = MagicMock()
    mock_resource.return_value.Table.return_value = table

    from lambdas.subscribe.handler import handler

    event = {
        "body": json.dumps({"user_id": "u1", "topic": "orders"}),
        "requestContext": {"requestId": "req-1"},
    }
    resp = handler(event, MagicMock())
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["topic"] == "orders"
    table.put_item.assert_called_once()


@patch("boto3.resource")
def test_subscribe_missing_fields(mock_resource):
    from lambdas.subscribe.handler import handler

    event = {"body": json.dumps({"user_id": "u1"}), "requestContext": {"requestId": "req-2"}}
    resp = handler(event, MagicMock())
    assert resp["statusCode"] == 400


@patch("boto3.resource")
def test_subscribe_empty_body(mock_resource):
    from lambdas.subscribe.handler import handler

    event = {"body": None, "requestContext": {"requestId": "req-3"}}
    resp = handler(event, MagicMock())
    assert resp["statusCode"] == 400

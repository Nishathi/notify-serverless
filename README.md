# Real-Time Notification System — Serverless Python on AWS

A production-grade, fully serverless notification platform built with Python and AWS.  
Clients subscribe to topics, publishers push messages, and subscribers receive them instantly over WebSocket — all without managing a single server.

---

## Architecture

```
┌─────────────┐     POST /subscriptions      ┌──────────────────┐
│   Client    │ ──────────────────────────► │  λ Subscribe     │
│ (browser /  │                              └────────┬─────────┘
│  service)   │     POST /publish                     │ DynamoDB
│             │ ──────────────────────────► ┌────────▼─────────┐
│             │                              │  λ Publish       │
│             │                              └────────┬─────────┘
│             │                                       │ SNS Topic
│             │                              ┌────────▼─────────┐
│             │                              │   SQS Queue      │
│             │                              │   (+ DLQ)        │
│             │                              └────────┬─────────┘
│             │                              ┌────────▼─────────┐
│             │   WebSocket push             │  λ Deliver       │
│             │ ◄──────────────────────────  │  (fan-out)       │
│             │                              └──────────────────┘
│             │   wss:// $connect/$disconnect ┌─────────────────┐
│             │ ──────────────────────────► │ λ WS Connect /   │
└─────────────┘                              │   Disconnect     │
                                             └──────────────────┘
```

### AWS Services Used

| Service | Purpose |
|---|---|
| **API Gateway HTTP API** | REST endpoints: `/subscriptions`, `/publish` |
| **API Gateway WebSocket API** | Real-time push to connected clients |
| **Lambda (×5)** | Subscribe, Publish, Deliver, WS Connect, WS Disconnect |
| **DynamoDB (×2)** | Subscriptions table, Connections table (with TTL) |
| **SNS** | Fan-out: one publish → all delivery workers |
| **SQS** | Buffered, reliable message queue with DLQ (3 retries) |
| **CDK** | All infrastructure as Python code |
| **GitHub Actions** | CI: lint + test; CD: OIDC deploy on merge to main |

---

## Key Design Decisions

**Why SNS → SQS instead of Lambda direct invocation?**  
SNS fan-out decouples the publisher from delivery. SQS adds buffering, retry logic, and a dead-letter queue — if delivery fails 3 times, the message lands in the DLQ for inspection rather than being lost.

**Why DynamoDB TTL on connections?**  
WebSocket connections that disconnect without a clean `$disconnect` event (e.g. network drop) leave stale records. TTL automatically expires them after 24 hours; the Deliver Lambda also cleans up `GoneException` connections on the fly.

**Why OIDC instead of IAM access keys in CI/CD?**  
No long-lived credentials stored in GitHub Secrets. GitHub exchanges a short-lived OIDC token for a temporary AWS role — the security best practice for GitHub Actions.

**Why ARM64 (Graviton2) for all Lambdas?**  
~20% cheaper and equal or faster cold-start performance for Python workloads.

---

## Project Structure

```
notify-serverless/
├── app.py                          # CDK entry point
├── infra/
│   └── stack.py                   # Full CDK stack
├── lambdas/
│   ├── subscribe/handler.py       # POST /subscriptions
│   ├── publish/handler.py         # POST /publish
│   ├── deliver/handler.py         # SNS→SQS consumer, WebSocket push
│   ├── ws_connect/handler.py      # WebSocket $connect
│   └── ws_disconnect/handler.py   # WebSocket $disconnect
├── tests/
│   └── unit/
│       ├── test_subscribe.py
│       └── test_publish.py
├── .github/workflows/deploy.yml   # CI/CD pipeline
└── pyproject.toml
```

---

## Local Setup

### Prerequisites

- Python 3.12+
- Node.js 20+ (for CDK CLI)
- AWS CLI configured (`aws configure`)
- An AWS account with CDK bootstrapped

```bash
# 1. Clone
git clone https://github.com/<your-username>/notify-serverless
cd notify-serverless

# 2. Install Python deps
pip install -e ".[dev]"

# 3. Install CDK
npm install -g aws-cdk

# 4. Run tests
pytest tests/unit -v

# 5. Bootstrap CDK (once per account/region)
cdk bootstrap

# 6. Deploy
cdk deploy NotificationStack
```

After deploy, CDK prints two outputs:
```
NotificationStack.HttpApiUrl = https://abc123.execute-api.ap-south-1.amazonaws.com
NotificationStack.WsApiUrl   = wss://xyz789.execute-api.ap-south-1.amazonaws.com/prod
```

---

## API Reference

### Subscribe to a topic

```http
POST /subscriptions
Content-Type: application/json

{
  "user_id": "user-123",
  "topic": "orders"
}
```

```json
// 201 Created
{ "message": "subscribed", "user_id": "user-123", "topic": "orders" }
```

### Publish a notification

```http
POST /publish
Content-Type: application/json

{
  "topic": "orders",
  "message": "Your order #42 has shipped!",
  "metadata": { "order_id": "42", "carrier": "FedEx" }
}
```

```json
// 202 Accepted
{ "notification_id": "uuid-...", "queued_for": 3 }
```

### WebSocket (receive notifications)

```javascript
// Connect (pass user_id as query param)
const ws = new WebSocket("wss://xyz789.execute-api.ap-south-1.amazonaws.com/prod?user_id=user-123");

ws.onmessage = (event) => {
  const notification = JSON.parse(event.data);
  console.log(notification.message);  // "Your order #42 has shipped!"
};
```

---

## End-to-End Demo

```bash
HTTP_URL="https://abc123.execute-api.ap-south-1.amazonaws.com"

# 1. Subscribe user-1 to "orders"
curl -X POST $HTTP_URL/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user-1","topic":"orders"}'

# 2. In another terminal, open a WebSocket and listen
wscat -c "wss://xyz789.execute-api.ap-south-1.amazonaws.com/prod?user_id=user-1"

# 3. Publish a notification
curl -X POST $HTTP_URL/publish \
  -H "Content-Type: application/json" \
  -d '{"topic":"orders","message":"Order #42 shipped!"}'

# → WebSocket terminal receives the notification in real time
```

---

## CI/CD Pipeline

Every push to `main`:

1. **Test** — ruff lint + black format check + pytest (≥70% coverage gate)
2. **Deploy** — OIDC-authenticated `cdk deploy` to `ap-south-1`

To set up:
1. Create an IAM role with OIDC trust for `token.actions.githubusercontent.com`
2. Add `AWS_DEPLOY_ROLE_ARN` to your GitHub repo secrets

---

## Cost Estimate (light usage)

All services have generous free tiers. At ~10,000 notifications/month:

| Service | Cost |
|---|---|
| Lambda (5 functions) | ~$0.00 (free tier) |
| DynamoDB | ~$0.00 (on-demand, free tier) |
| SNS | ~$0.01 |
| SQS | ~$0.00 (free tier) |
| API Gateway (HTTP + WS) | ~$0.04 |
| **Total** | **< $0.10/month** |

---

## Tech Stack

- **Runtime**: Python 3.12 on AWS Lambda (ARM64/Graviton2)
- **Observability**: [AWS Lambda Powertools](https://docs.powertools.aws.dev/lambda/python/) — structured logging, tracing, batch processing
- **IaC**: AWS CDK v2 (Python)
- **Testing**: pytest + moto (AWS mocking)
- **CI/CD**: GitHub Actions with OIDC

---

## Author

Built as an internship project demonstrating serverless architecture patterns on AWS.

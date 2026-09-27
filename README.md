# Ticket Stampede

A concurrency-safe ticket-selling service built with:

* Python
* FastAPI
* Redis
* asyncio
* HTTPX
* Docker Compose

The project demonstrates the difference between a **naive non-atomic implementation** and a **Redis-based atomic implementation** under concurrent load.

The main focus is:

* Correctness
* Atomic ticket allocation
* Request idempotency
* Reproducible concurrency testing

---

## 1. Architecture

```text
              Load Test Client
              asyncio + HTTPX
                     |
                     | HTTP
                     v
              FastAPI Seller
               /reset /buy
                 /status
                     |
                     | Redis
                     v
                   Redis
```

The fixed seller stores all shared ticket state in Redis.

The critical `/buy` operation is implemented using a Redis Lua script.

The script atomically:

```text
1. Check request ID
2. Allocate an available ticket
3. Record ticket ownership
4. Record request ID -> ticket mapping
5. Increment sold count
```

This prevents concurrent requests from interleaving during ticket allocation.

---

## 2. Project Structure

```text
ticket-stampede/
│
├── seller/
│   ├── __init__.py
│   ├── main.py              # Redis-based fixed seller
│   ├── naive_main.py        # Deliberately unsafe seller
│   └── lua/
│       └── buy.lua          # Atomic allocation script
│
├── load_test/
│   └── load_test.py         # Async concurrent load tester
│
├── tests/
│   └── test_invariants.py   # Automated correctness tests
│
├── logs/
│   ├── README.md
│   ├── naive-1000-100.txt
│   ├── fixed-1000-100.txt
│   └── pytest-results.txt
│
├── README.md
├── DECISIONS.md
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

# 3. Requirements

For the seller:

* Docker
* Docker Compose

For tests and load testing:

* Python 3.11+

No frontend or additional infrastructure is required.

---

# 4. Run the Fixed Seller

From the project root:

```bash
docker compose up --build -d
```

Check that the containers are running:

```bash
docker compose ps
```

The seller runs at:

```text
http://localhost:8000
```

Check the API:

```bash
curl http://localhost:8000/status
```

---

# 5. API

## Reset

Create a new sale with 100 tickets:

```bash
curl -X POST http://localhost:8000/reset \
  -H "Content-Type: application/json" \
  -d '{"ticket_count":100}'
```

Response:

```json
{
  "message": "reset",
  "ticket_count": 100
}
```

---

## Buy

```bash
curl -X POST http://localhost:8000/buy \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user-1","request_id":"req-1"}'
```

Example response:

```json
{
  "ticket_number": 42,
  "user_id": "user-1",
  "request_id": "req-1"
}
```

The exact ticket number may differ between runs.

---

## Status

```bash
curl http://localhost:8000/status
```

Example:

```json
{
  "ticket_count": 100,
  "sold_count": 1,
  "remaining_count": 99,
  "tickets": [
    {
      "ticket_number": 42,
      "user_id": "user-1"
    }
  ]
}
```

---

# 6. Idempotency

The same `request_id` never consumes another ticket.

For example, sending:

```json
{
  "user_id": "user-1",
  "request_id": "req-1"
}
```

and then:

```json
{
  "user_id": "user-2",
  "request_id": "req-1"
}
```

returns the same ticket for both requests.

The request ID → ticket mapping and ticket allocation happen inside the same Redis Lua script, so this remains safe even when duplicate requests arrive concurrently.

---

# 7. Automated Tests

Create a Python environment if needed:

### Windows

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Make sure the fixed seller is running:

```bash
docker compose up --build -d
```

Run:

```bash
pytest -v
```

The tests cover:

* Reset
* Successful purchase
* Duplicate request ID
* Sold-out behavior
* Unique ticket numbers
* Status consistency
* Concurrent purchases

### Actual Test Result

```text
7 passed in 55.41s
```

All seven tests passed, including the concurrency test. The complete output is preserved in:

```text
logs/pytest-results.txt
```

---

# 8. Load Test

The load tester is:

```text
load_test/load_test.py
```

It uses `asyncio` and `httpx`.

It:

1. Resets the seller.
2. Generates users and request IDs.
3. Replays duplicate request IDs.
4. Sends concurrent `/buy` requests.
5. Records responses and latency.
6. Calls `/status`.
7. Checks the four required invariants.
8. Prints performance metrics and PASS/FAIL results.

---

# 9. Fixed Implementation Experiment

Run the fixed seller:

```bash
docker compose up --build -d
```

Run the load test:

```bash
python load_test/load_test.py \
  --url http://localhost:8000 \
  --tickets 100 \
  --requests 1000 \
  --concurrency 100 \
  --duplicates 200
```

Windows PowerShell:

```powershell
python load_test\load_test.py --url http://localhost:8000 --tickets 100 --requests 1000 --concurrency 100 --duplicates 200
```

## Actual Result

Workload:

```text
Tickets:      100
Requests:     1000
Concurrency:  100
Duplicates:   200
```

Measured results:

```text
Total requests:       1000
Successful purchases: 137
Sold out:             863
Errors:               0

Requests/sec:         37.66
Median latency:       1521.86 ms
P99 latency:          13065.96 ms
Total execution time: 26.55 s
```

Final state:

```text
Configured tickets: 100
Sold:               100
Remaining:          0
Ownership records:  100
```

Invariants:

```text
Never oversold:          PASS
No duplicate tickets:   PASS
Request idempotency:    PASS
Status consistency:     PASS

OVERALL: PASS
```

The complete raw output is preserved in:

```text
logs/fixed-1000-100.txt
```

### Why were there 137 successful purchases with only 100 tickets?

There were 200 duplicate request-ID replays.

A duplicate request is considered a successful response because it returns the ticket previously assigned to that request ID. It does **not** consume another ticket.

The final Redis state therefore correctly contains exactly 100 sold tickets.

---

# 10. Naive Implementation Experiment

The naive implementation intentionally performs ticket allocation using non-atomic application-level state.

Start it:

```bash
python -m uvicorn seller.naive_main:app --host 127.0.0.1 --port 8001
```

In another terminal, run the same workload:

```bash
python load_test/load_test.py \
  --url http://localhost:8001 \
  --tickets 100 \
  --requests 1000 \
  --concurrency 100 \
  --duplicates 200
```

Windows PowerShell:

```powershell
python load_test\load_test.py --url http://localhost:8001 --tickets 100 --requests 1000 --concurrency 100 --duplicates 200
```

## Actual Result

```text
Total requests:       1000
Successful purchases: 104
Sold out:             896
Errors:               0

Requests/sec:         28.35
Median latency:       1940.16 ms
P99 latency:          16454.34 ms
Total execution time: 35.28 s
```

Final state:

```text
Configured tickets: 100
Sold:               104
Remaining:          0
Ownership records:  104
```

Invariants:

```text
Never oversold:          FAIL
No duplicate tickets:   FAIL
Request idempotency:    FAIL
Status consistency:     FAIL

OVERALL: FAIL
```

The test detected:

```text
Oversold: sold_count=104, ticket_count=100
Duplicate or invalid ticket numbers
At least one request_id received multiple tickets
Status counts do not match issued tickets
```

The complete raw output is preserved in:

```text
logs/naive-1000-100.txt
```

---

# 11. Redis Data Model

The fixed implementation uses:

| Redis key           | Type   | Purpose                      |
| ------------------- | ------ | ---------------------------- |
| `ticket:count`      | String | Configured ticket count      |
| `ticket:sold_count` | String | Number of allocated tickets  |
| `ticket:available`  | Set    | Available ticket numbers     |
| `ticket:requests`   | Hash   | `request_id → ticket_number` |
| `ticket:owners`     | Hash   | `ticket_number → user_id`    |

The critical allocation operation is implemented in:

```text
seller/lua/buy.lua
```

# 12. Logs and Reproducibility

The `logs/` directory contains:

```text
logs/
├── README.md
├── naive-1000-100.txt
├── fixed-1000-100.txt
└── pytest-results.txt
```

These contain the actual outputs from the experiments and automated tests.

No benchmark values in this README are manually invented; they correspond to the recorded experiment outputs.

---

# 13. Quick Points for Evaluation


### 1. Start the seller

```bash
docker compose up --build -d
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Run automated tests

```bash
pytest -v
```

### 4. Run the fixed concurrency test

```bash
python load_test/load_test.py --url http://localhost:8000 --tickets 100 --requests 1000 --concurrency 100 --duplicates 200
```

### 5. Run the naive comparison

Start:

```bash
python -m uvicorn seller.naive_main:app --host 127.0.0.1 --port 8001
```

Then:

```bash
python load_test/load_test.py --url http://localhost:8001 --tickets 100 --requests 1000 --concurrency 100 --duplicates 200
```

### 6. Stop Docker

```bash
docker compose down
```

---


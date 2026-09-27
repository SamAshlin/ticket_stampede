# Design Decisions

## 1. Architecture and Technology Choices

The system uses **Python, FastAPI, Redis, Redis Lua, asyncio, httpx, pytest, and Docker Compose**.

* **Python** — Required by the assignment and suitable for quickly implementing the API, concurrency logic, and load-testing client.
* **FastAPI** — Used for the REST API because it provides simple endpoint definitions and asynchronous request handling. The required endpoints are `/reset`, `/buy`, and `/status`.
* **Redis** — Used as the shared state store because ticket inventory must be coordinated across concurrent requests and potentially multiple seller instances. In-memory Python state would not provide this shared coordination.
* **Redis Set** — Used for available tickets. `SPOP` removes an available ticket atomically, preventing the same ticket from being allocated twice.
* **Redis Hashes** — Used for `request_id → ticket` and `ticket → user` mappings, providing idempotency and ownership tracking.
* **Redis Lua** — Used for the critical purchase operation. Checking the request ID, allocating a ticket, recording ownership, and incrementing the counter must happen atomically. Lua allows these operations to execute as one Redis operation.
* **asyncio** — Used for asynchronous API handling and to create a reproducible race window in the naive implementation.
* **httpx** — Used by the load-test client to generate concurrent HTTP requests.
* **pytest** — Used to verify the required invariants through automated tests.
* **Docker Compose** — Used to run the seller and Redis together in a reproducible environment.

### What I rejected

* **In-memory state:** rejected because it does not provide shared state between multiple service instances.
* **`asyncio.Lock`:** rejected as the primary concurrency mechanism because it only protects a single application process.
* **Database transactions:** possible, but Redis provides a simpler atomic allocation mechanism for this assignment.
* **Frontend:** not implemented because the task evaluates the backend concurrency guarantees.

---

## 2. Trade-offs Under the Time Limit

The main priority was **correctness under concurrency**, rather than building a complete production ticketing platform.

I kept the design deliberately small:

* Redis Lua instead of a more complex distributed-locking system.
* Redis Set instead of maintaining sequential allocation state.
* `/status` exposes ownership information to make invariant validation easy.
* Redis failures return errors rather than falsely reporting successful purchases.
* Authentication, rate limiting, Redis replication/failover, monitoring, and cloud deployment were left out because they were outside the assignment's time limit.

The naive implementation was intentionally kept unsafe so the race condition could be demonstrated experimentally.

---

## 3. How I Tested It

Testing was done at two levels.

### Automated tests

`pytest` tests:

* reset
* successful purchase
* duplicate request IDs
* sold-out behavior
* unique ticket numbers
* status consistency
* concurrent purchases

Result: **7/7 tests passed.**

### Load test

Both implementations were tested with the same workload:

* 100 tickets
* 1,000 requests
* 100 concurrent requests
* duplicate request IDs

The **naive implementation oversold**, recording 104 tickets for a 100-ticket sale.

The **Redis/Lua implementation sold exactly 100 tickets** and passed all required invariants.

The actual outputs are preserved in `logs/`.

---

## 4. Where It Breaks

The system assumes Redis is available. If Redis becomes unavailable, the service returns an error rather than pretending the purchase succeeded.

Other limitations:

* No Redis replication or automatic failover.
* No authentication or rate limiting.
* No multi-region deployment.
* `/status` returns ownership information, which would become expensive for a very large sale.
* Load-test results are primarily for correctness validation, not production capacity planning.

The core concurrency guarantees depend on Redis remaining the authoritative shared state.

---

## 5. What I Would Improve Next

With additional time I would:

1. Add Redis replication, persistence, failover, and monitoring.
2. Add authentication, rate limiting, and stronger API validation.
3. Perform larger controlled load and latency tests.
4. Add structured logging, metrics, and tracing.
5. Add failure-injection and recovery tests.
6. Set up production deployment and CI/CD.
7. Improve `/status` so large ownership datasets do not need to be returned in one response.


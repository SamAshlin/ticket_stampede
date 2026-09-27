import argparse
import asyncio
import statistics
import time
from collections import defaultdict

import httpx


async def send_buy(client, url, user_id, request_id, semaphore):
    async with semaphore:
        start = time.perf_counter()

        try:
            response = await client.post(
                f"{url}/buy",
                json={
                    "user_id": user_id,
                    "request_id": request_id,
                },
            )

            latency_ms = (time.perf_counter() - start) * 1000

            try:
                body = response.json()
            except Exception:
                body = {}

            return {
                "status_code": response.status_code,
                "body": body,
                "latency_ms": latency_ms,
                "request_id": request_id,
            }

        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000

            return {
                "status_code": None,
                "body": {},
                "latency_ms": latency_ms,
                "request_id": request_id,
                "error": str(exc),
            }


def percentile(values, p):
    if not values:
        return 0.0

    values = sorted(values)

    index = int((p / 100) * (len(values) - 1))

    return values[index]


def validate_invariants(results, status):
    failures = []

    ticket_count = status["ticket_count"]
    sold_count = status["sold_count"]
    remaining_count = status["remaining_count"]
    tickets = status["tickets"]

    # -----------------------------------
    # Invariant 1: never oversold
    # -----------------------------------

    never_oversold = sold_count <= ticket_count

    if not never_oversold:
        failures.append(
            f"Oversold: sold_count={sold_count}, "
            f"ticket_count={ticket_count}"
        )

    # -----------------------------------
    # Invariant 2: unique ticket numbers
    # -----------------------------------

    ticket_numbers = [
        ticket["ticket_number"]
        for ticket in tickets
    ]

    no_duplicate_tickets = (
        len(ticket_numbers) == len(set(ticket_numbers))
        and all(1 <= n <= ticket_count for n in ticket_numbers)
    )

    if not no_duplicate_tickets:
        failures.append("Duplicate or invalid ticket numbers detected")

    # -----------------------------------
    # Invariant 3: request ID idempotency
    # -----------------------------------

    request_to_tickets = defaultdict(set)

    for result in results:
        if result["status_code"] == 200:
            body = result["body"]

            request_id = body.get("request_id")
            ticket_number = body.get("ticket_number")

            if request_id is not None and ticket_number is not None:
                request_to_tickets[request_id].add(ticket_number)

    idempotent = all(
        len(ticket_numbers_for_request) == 1
        for ticket_numbers_for_request
        in request_to_tickets.values()
    )

    if not idempotent:
        failures.append(
            "At least one request_id received multiple tickets"
        )

    # -----------------------------------
    # Invariant 4: status consistency
    # -----------------------------------

    status_consistent = (
        sold_count == len(tickets)
        and sold_count + remaining_count == ticket_count
    )

    if not status_consistent:
        failures.append(
            "Status counts do not match issued tickets"
        )

    return {
        "never_oversold": never_oversold,
        "no_duplicate_tickets": no_duplicate_tickets,
        "request_idempotency": idempotent,
        "status_consistency": status_consistent,
        "failures": failures,
    }


async def run_load_test(args):
    url = args.url.rstrip("/")

    if args.duplicates is not None and args.duplicate_percent is not None:
        raise ValueError(
            "Use either --duplicates or --duplicate-percent, not both."
        )

    duplicate_count = args.duplicates or 0

    if args.duplicate_percent is not None:
        duplicate_count = round(
            args.requests * args.duplicate_percent / 100
        )

    if duplicate_count >= args.requests:
        raise ValueError(
            "Number of duplicates must be smaller than total requests."
        )

    print()
    print("Resetting seller...")

    async with httpx.AsyncClient(
        timeout=30.0,
        limits=httpx.Limits(
            max_connections=args.concurrency * 2,
            max_keepalive_connections=args.concurrency,
        ),
    ) as client:

        reset_response = await client.post(
            f"{url}/reset",
            json={
                "ticket_count": args.tickets,
            },
        )

        if reset_response.status_code != 200:
            print("Reset failed:")
            print(reset_response.text)
            return

        # -----------------------------------------
        # Generate request IDs
        # -----------------------------------------

        unique_request_count = args.requests - duplicate_count

        unique_requests = [
            (
                f"user-{i}",
                f"request-{i}",
            )
            for i in range(unique_request_count)
        ]

        requests = list(unique_requests)

        # Intentionally replay some existing request IDs.
        for i in range(duplicate_count):
            user_id, request_id = unique_requests[
                i % len(unique_requests)
            ]

            requests.append(
                (
                    f"duplicate-user-{i}",
                    request_id,
                )
            )

        # Shuffle to make duplicate requests arrive
        # at unpredictable points in the concurrency window.
        import random

        random.shuffle(requests)

        semaphore = asyncio.Semaphore(args.concurrency)

        print()
        print("Starting load test...")
        print(f"Seller URL:       {url}")
        print(f"Total requests:   {len(requests)}")
        print(f"Tickets:          {args.tickets}")
        print(f"Concurrency:      {args.concurrency}")
        print(f"Duplicates:       {duplicate_count}")

        start_time = time.perf_counter()

        tasks = [
            send_buy(
                client,
                url,
                user_id,
                request_id,
                semaphore,
            )
            for user_id, request_id in requests
        ]

        results = await asyncio.gather(*tasks)

        total_time = time.perf_counter() - start_time

        # -----------------------------------------
        # Metrics
        # -----------------------------------------

        successful = [
            r for r in results
            if r["status_code"] == 200
        ]

        sold_out = [
            r for r in results
            if r["status_code"] == 409
        ]

        errors = [
            r for r in results
            if r["status_code"] not in (200, 409)
        ]

        latencies = [
            r["latency_ms"]
            for r in results
        ]

        rps = (
            len(results) / total_time
            if total_time > 0
            else 0
        )

        median_latency = (
            statistics.median(latencies)
            if latencies
            else 0
        )

        p99_latency = percentile(latencies, 99)

        # -----------------------------------------
        # Status
        # -----------------------------------------

        print()
        print("Fetching final status...")

        status_response = await client.get(
            f"{url}/status"
        )

        if status_response.status_code != 200:
            print("Could not fetch /status")
            return

        status = status_response.json()

        # -----------------------------------------
        # Validate
        # -----------------------------------------

        invariants = validate_invariants(
            results,
            status,
        )

        print()
        print("========== LOAD TEST ==========")
        print()
        print(f"Total requests:       {len(results)}")
        print(f"Successful purchases: {len(successful)}")
        print(f"Sold out:             {len(sold_out)}")
        print(f"Errors:               {len(errors)}")
        print()
        print(f"Requests/sec:         {rps:.2f}")
        print(f"Median latency:       {median_latency:.2f} ms")
        print(f"P99 latency:          {p99_latency:.2f} ms")
        print(f"Total execution time: {total_time:.2f} s")

        print()
        print("========== FINAL STATUS ==========")
        print()
        print(f"Configured tickets: {status['ticket_count']}")
        print(f"Sold:               {status['sold_count']}")
        print(f"Remaining:          {status['remaining_count']}")
        print(f"Ownership records:  {len(status['tickets'])}")

        print()
        print("========== INVARIANTS ==========")
        print()

        print(
            "Never oversold:          "
            + ("PASS" if invariants["never_oversold"] else "FAIL")
        )

        print(
            "No duplicate tickets:    "
            + (
                "PASS"
                if invariants["no_duplicate_tickets"]
                else "FAIL"
            )
        )

        print(
            "Request idempotency:     "
            + (
                "PASS"
                if invariants["request_idempotency"]
                else "FAIL"
            )
        )

        print(
            "Status consistency:      "
            + (
                "PASS"
                if invariants["status_consistency"]
                else "FAIL"
            )
        )

        overall_pass = all(
            [
                invariants["never_oversold"],
                invariants["no_duplicate_tickets"],
                invariants["request_idempotency"],
                invariants["status_consistency"],
                len(errors) == 0,
            ]
        )

        print()
        print(
            "OVERALL: "
            + ("PASS" if overall_pass else "FAIL")
        )

        if invariants["failures"]:
            print()
            print("Failures:")

            for failure in invariants["failures"]:
                print(f"- {failure}")

        if errors:
            print()
            print("Example errors:")

            for error in errors[:5]:
                print(error)

        print()


def main():
    parser = argparse.ArgumentParser(
        description="Ticket Stampede load tester"
    )

    parser.add_argument(
        "--url",
        required=True,
        help="Seller URL, e.g. http://localhost:8000",
    )

    parser.add_argument(
        "--requests",
        type=int,
        default=1000,
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=100,
    )

    parser.add_argument(
        "--tickets",
        type=int,
        default=100,
    )

    parser.add_argument(
        "--duplicates",
        type=int,
        default=None,
        help="Number of duplicate request replays",
    )

    parser.add_argument(
        "--duplicate-percent",
        type=float,
        default=None,
        help="Percentage of requests that are duplicate replays",
    )

    args = parser.parse_args()

    asyncio.run(run_load_test(args))


if __name__ == "__main__":
    main()
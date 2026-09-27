import asyncio
import os

import httpx


BASE_URL = os.getenv(
    "SELLER_URL",
    "http://localhost:8000",
)


def post_buy(client, user_id, request_id):
    return client.post(
        f"{BASE_URL}/buy",
        json={
            "user_id": user_id,
            "request_id": request_id,
        },
    )


def test_reset():
    response = httpx.post(
        f"{BASE_URL}/reset",
        json={"ticket_count": 5},
        timeout=10,
    )

    assert response.status_code == 200

    status = httpx.get(
        f"{BASE_URL}/status",
        timeout=10,
    ).json()

    assert status["ticket_count"] == 5
    assert status["sold_count"] == 0
    assert status["remaining_count"] == 5
    assert status["tickets"] == []


def test_successful_purchase():
    httpx.post(
        f"{BASE_URL}/reset",
        json={"ticket_count": 5},
        timeout=10,
    )

    response = httpx.post(
        f"{BASE_URL}/buy",
        json={
            "user_id": "user-1",
            "request_id": "req-1",
        },
        timeout=10,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["user_id"] == "user-1"
    assert body["request_id"] == "req-1"
    assert 1 <= body["ticket_number"] <= 5


def test_duplicate_request_id():
    httpx.post(
        f"{BASE_URL}/reset",
        json={"ticket_count": 5},
        timeout=10,
    )

    first = httpx.post(
        f"{BASE_URL}/buy",
        json={
            "user_id": "user-1",
            "request_id": "same-request",
        },
        timeout=10,
    )

    second = httpx.post(
        f"{BASE_URL}/buy",
        json={
            "user_id": "user-2",
            "request_id": "same-request",
        },
        timeout=10,
    )

    assert first.status_code == 200
    assert second.status_code == 200

    assert (
        first.json()["ticket_number"]
        == second.json()["ticket_number"]
    )

    status = httpx.get(
        f"{BASE_URL}/status",
        timeout=10,
    ).json()

    assert status["sold_count"] == 1


def test_sold_out():
    httpx.post(
        f"{BASE_URL}/reset",
        json={"ticket_count": 2},
        timeout=10,
    )

    first = httpx.post(
        f"{BASE_URL}/buy",
        json={
            "user_id": "user-1",
            "request_id": "req-1",
        },
        timeout=10,
    )

    second = httpx.post(
        f"{BASE_URL}/buy",
        json={
            "user_id": "user-2",
            "request_id": "req-2",
        },
        timeout=10,
    )

    third = httpx.post(
        f"{BASE_URL}/buy",
        json={
            "user_id": "user-3",
            "request_id": "req-3",
        },
        timeout=10,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 409


def test_unique_ticket_numbers():
    httpx.post(
        f"{BASE_URL}/reset",
        json={"ticket_count": 20},
        timeout=10,
    )

    for i in range(20):
        response = httpx.post(
            f"{BASE_URL}/buy",
            json={
                "user_id": f"user-{i}",
                "request_id": f"req-{i}",
            },
            timeout=10,
        )

        assert response.status_code == 200

    status = httpx.get(
        f"{BASE_URL}/status",
        timeout=10,
    ).json()

    ticket_numbers = [
        ticket["ticket_number"]
        for ticket in status["tickets"]
    ]

    assert len(ticket_numbers) == 20
    assert len(ticket_numbers) == len(
        set(ticket_numbers)
    )


def test_status_consistency():
    httpx.post(
        f"{BASE_URL}/reset",
        json={"ticket_count": 20},
        timeout=10,
    )

    for i in range(7):
        httpx.post(
            f"{BASE_URL}/buy",
            json={
                "user_id": f"user-{i}",
                "request_id": f"req-{i}",
            },
            timeout=10,
        )

    status = httpx.get(
        f"{BASE_URL}/status",
        timeout=10,
    ).json()

    assert (
        status["sold_count"]
        == len(status["tickets"])
    )

    assert (
        status["sold_count"]
        + status["remaining_count"]
        == status["ticket_count"]
    )


def test_concurrent_invariants():
    httpx.post(
        f"{BASE_URL}/reset",
        json={"ticket_count": 100},
        timeout=10,
    )

    async def run():
        limits = httpx.Limits(
            max_connections=100,
            max_keepalive_connections=100,
        )

        async with httpx.AsyncClient(
            limits=limits,
            timeout=30,
        ) as client:

            tasks = []

            for i in range(500):
                tasks.append(
                    client.post(
                        f"{BASE_URL}/buy",
                        json={
                            "user_id": f"user-{i}",
                            "request_id": f"req-{i}",
                        },
                    )
                )

            return await asyncio.gather(*tasks)

    responses = asyncio.run(run())

    successful = [
        response
        for response in responses
        if response.status_code == 200
    ]

    sold_out = [
        response
        for response in responses
        if response.status_code == 409
    ]

    assert len(successful) == 100
    assert len(sold_out) == 400

    status = httpx.get(
        f"{BASE_URL}/status",
        timeout=10,
    ).json()

    tickets = status["tickets"]

    ticket_numbers = [
        ticket["ticket_number"]
        for ticket in tickets
    ]

    assert status["sold_count"] == 100
    assert status["remaining_count"] == 0

    assert len(ticket_numbers) == 100
    assert len(ticket_numbers) == len(
        set(ticket_numbers)
    )

    assert (
        status["sold_count"]
        + status["remaining_count"]
        == status["ticket_count"]
    )
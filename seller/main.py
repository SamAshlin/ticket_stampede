import os
from pathlib import Path

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="Ticket Stampede - Redis Seller")


REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://localhost:6379/0",
)

AVAILABLE_KEY = "ticket:available"
REQUEST_KEY = "ticket:requests"
OWNER_KEY = "ticket:owners"
SOLD_KEY = "ticket:sold_count"
COUNT_KEY = "ticket:count"


redis_client = redis.from_url(
    REDIS_URL,
    decode_responses=True,
)


BUY_LUA = (
    Path(__file__).parent
    / "lua"
    / "buy.lua"
).read_text()


STATUS_LUA = """
local ticket_count =
    redis.call("GET", KEYS[1]) or "0"

local sold_count =
    redis.call("GET", KEYS[2]) or "0"

local remaining_count =
    redis.call("SCARD", KEYS[3])

local ownership =
    redis.call("HGETALL", KEYS[4])

local result = {
    ticket_count,
    sold_count,
    remaining_count
}

for _, value in ipairs(ownership) do
    table.insert(result, value)
end

return result
"""


class ResetRequest(BaseModel):
    ticket_count: int = Field(
        gt=0,
        le=1_000_000,
    )


class BuyRequest(BaseModel):
    user_id: str = Field(
        min_length=1,
        max_length=256,
    )

    request_id: str = Field(
        min_length=1,
        max_length=256,
    )


@app.on_event("startup")
async def startup():
    try:
        await redis_client.ping()
    except redis.RedisError as exc:
        print(f"Redis unavailable during startup: {exc}")


@app.on_event("shutdown")
async def shutdown():
    await redis_client.aclose()


@app.post("/reset")
async def reset(request: ResetRequest):
    try:
        tickets = [
            str(i)
            for i in range(
                1,
                request.ticket_count + 1,
            )
        ]

        async with redis_client.pipeline(
            transaction=True
        ) as pipe:

            pipe.delete(
                AVAILABLE_KEY,
                REQUEST_KEY,
                OWNER_KEY,
                SOLD_KEY,
                COUNT_KEY,
            )

            pipe.set(
                COUNT_KEY,
                request.ticket_count,
            )

            pipe.set(
                SOLD_KEY,
                0,
            )

            pipe.sadd(
                AVAILABLE_KEY,
                *tickets,
            )

            await pipe.execute()

        return {
            "message": "reset",
            "ticket_count": request.ticket_count,
        }

    except redis.RedisError as exc:
        raise HTTPException(
            status_code=503,
            detail="Redis unavailable",
        ) from exc


@app.post("/buy")
async def buy(request: BuyRequest):
    try:
        result = await redis_client.eval(
            BUY_LUA,
            4,
            AVAILABLE_KEY,
            REQUEST_KEY,
            OWNER_KEY,
            SOLD_KEY,
            request.request_id,
            request.user_id,
        )

        result_type = result[0]

        if result_type == "SOLD_OUT":
            raise HTTPException(
                status_code=409,
                detail="sold_out",
            )

        if result_type == "DUPLICATE":
            ticket_number = int(result[1])

            return {
                "ticket_number": ticket_number,
                "user_id": request.user_id,
                "request_id": request.request_id,
            }

        if result_type == "SUCCESS":
            ticket_number = int(result[1])

            return {
                "ticket_number": ticket_number,
                "user_id": request.user_id,
                "request_id": request.request_id,
            }

        raise HTTPException(
            status_code=500,
            detail="unexpected_allocation_result",
        )

    except HTTPException:
        raise

    except redis.RedisError as exc:
        # VERY IMPORTANT:
        # Never return success if Redis failed.
        raise HTTPException(
            status_code=503,
            detail="Redis unavailable; purchase not confirmed",
        ) from exc


@app.get("/status")
async def status():
    try:
        result = await redis_client.eval(
            STATUS_LUA,
            4,
            COUNT_KEY,
            SOLD_KEY,
            AVAILABLE_KEY,
            OWNER_KEY,
        )

        ticket_count = int(result[0])
        sold_count = int(result[1])
        remaining_count = int(result[2])

        ownership = []

        # result[3:] contains:
        #
        # ticket_number, user_id,
        # ticket_number, user_id, ...

        values = result[3:]

        for i in range(0, len(values), 2):
            ticket_number = int(values[i])
            user_id = values[i + 1]

            ownership.append(
                {
                    "ticket_number": ticket_number,
                    "user_id": user_id,
                }
            )

        ownership.sort(
            key=lambda item: item["ticket_number"]
        )

        return {
            "ticket_count": ticket_count,
            "sold_count": sold_count,
            "remaining_count": remaining_count,
            "tickets": ownership,
        }

    except redis.RedisError as exc:
        raise HTTPException(
            status_code=503,
            detail="Redis unavailable",
        ) from exc
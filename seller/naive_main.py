import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Ticket Stampede - Naive Seller")


class ResetRequest(BaseModel):
    ticket_count: int = Field(gt=0, le=1_000_000)


class BuyRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=256)
    request_id: str = Field(min_length=1, max_length=256)


ticket_count = 0
sold_count = 0

# Keep every issued sale as a record.
# This intentionally allows duplicate ticket numbers to become visible.
issued_tickets = []


@app.post("/reset")
async def reset(request: ResetRequest):
    global ticket_count, sold_count, issued_tickets

    ticket_count = request.ticket_count
    sold_count = 0
    issued_tickets = []

    return {
        "message": "reset",
        "ticket_count": ticket_count,
    }


@app.post("/buy")
async def buy(request: BuyRequest):
    global sold_count

    # -----------------------------
    # DELIBERATELY NAIVE CODE
    # -----------------------------

    if sold_count >= ticket_count:
        raise HTTPException(
            status_code=409,
            detail="sold_out",
        )

    # Artificial delay makes the race easier to reproduce.
    await asyncio.sleep(0.005)

    # Multiple requests can reach this point after seeing
    # the same sold_count.
    ticket_number = sold_count + 1

    # Another scheduling point makes it possible for multiple
    # requests to calculate the same ticket number.
    await asyncio.sleep(0.005)

    sold_count += 1

    issued_tickets.append(
        {
            "ticket_number": ticket_number,
            "user_id": request.user_id,
            "request_id": request.request_id,
        }
    )

    return {
        "ticket_number": ticket_number,
        "user_id": request.user_id,
        "request_id": request.request_id,
    }


@app.get("/status")
async def status():
    remaining = max(ticket_count - sold_count, 0)

    return {
        "ticket_count": ticket_count,
        "sold_count": sold_count,
        "remaining_count": remaining,
        "tickets": issued_tickets,
    }
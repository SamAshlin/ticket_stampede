-- KEYS[1] = available tickets set
-- KEYS[2] = request_id -> ticket hash
-- KEYS[3] = ticket -> user_id hash
-- KEYS[4] = sold count
--
-- ARGV[1] = request_id
-- ARGV[2] = user_id

-- --------------------------------------------------
-- 1. Idempotency check
-- --------------------------------------------------

local existing_ticket =
    redis.call("HGET", KEYS[2], ARGV[1])

if existing_ticket then
    return {
        "DUPLICATE",
        existing_ticket
    }
end

-- --------------------------------------------------
-- 2. Allocate one available ticket
-- --------------------------------------------------

local ticket =
    redis.call("SPOP", KEYS[1])

if not ticket then
    return {
        "SOLD_OUT"
    }
end

-- --------------------------------------------------
-- 3. Record ownership
-- --------------------------------------------------

redis.call(
    "HSET",
    KEYS[3],
    ticket,
    ARGV[2]
)

-- --------------------------------------------------
-- 4. Record request -> ticket mapping
-- --------------------------------------------------

redis.call(
    "HSET",
    KEYS[2],
    ARGV[1],
    ticket
)

-- --------------------------------------------------
-- 5. Increment sold count
-- --------------------------------------------------

local sold_count =
    redis.call("INCR", KEYS[4])

return {
    "SUCCESS",
    ticket,
    sold_count
}
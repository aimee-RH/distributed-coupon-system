local token = redis.call('GET', KEYS[2])
if token then
    if token == ARGV[1] then return 3 end
    return 2
end
local stock = tonumber(redis.call('GET', KEYS[1]))
if not stock then return 4 end
if stock <= 0 then return 1 end
redis.call('DECR', KEYS[1])
redis.call('SET', KEYS[2], ARGV[1])
return 0

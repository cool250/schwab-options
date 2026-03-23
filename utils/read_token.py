import json
import os
import redis
from utils.utils import TOKEN_FILE_PATH

# Define the file path as a constant
FILE_PATH = TOKEN_FILE_PATH

REDIS_TOKEN_KEY = "TOKEN_JSON"

def _get_redis() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    return redis.from_url(url, decode_responses=True)

def _use_db() -> bool:
    return os.getenv("USE_DB", "").lower() in ("1", "true", "yes")

def save_token(data: dict) -> None:
    if _use_db():
        _get_redis().set(REDIS_TOKEN_KEY, json.dumps(data))
    else:
        with open(FILE_PATH, 'w') as file:
            json.dump(data, file, indent=4)

def read_token() -> dict:
    if _use_db():
        raw = _get_redis().get(REDIS_TOKEN_KEY)
        if raw:
            return json.loads(raw)
        # Fall back to TOKEN_JSON env var and seed Redis with it
        env_token = os.getenv("TOKEN_JSON")
        if env_token:
            _get_redis().set(REDIS_TOKEN_KEY, env_token)
            return json.loads(env_token)
        raise ValueError("Token not found in Redis or TOKEN_JSON env var.")
    env_token = os.getenv("TOKEN_JSON")
    if env_token:
        return json.loads(env_token)
    with open(FILE_PATH, 'r') as file:
        return json.load(file)

def get_response_token() -> str:
    data = read_token()
    return data.get("refresh_token", "Token not found")

def get_access_token() -> str:
    data = read_token()
    return data.get("access_token", "Token not found")

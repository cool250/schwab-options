import json
import os
import redis
from utils.utils import TOKEN_FILE_PATH

# Define the file path as a constant
FILE_PATH = TOKEN_FILE_PATH

REDIS_TOKEN_KEY = "schwab_token"

def _get_redis() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    return redis.from_url(url, decode_responses=True)

def _use_db() -> bool:
    return os.getenv("USE_DB", "").lower() in ("1", "true", "yes")

def save_dict_to_file(data: dict) -> None:
    if _use_db():
        _get_redis().set(REDIS_TOKEN_KEY, json.dumps(data))
    else:
        with open(FILE_PATH, 'w') as file:
            json.dump(data, file, indent=4)

def read_dict_from_file() -> dict:
    if _use_db():
        raw = _get_redis().get(REDIS_TOKEN_KEY)
        if raw:
            return json.loads(raw)
        raise ValueError("Token not found in Redis. Set the token first.")
    env_token = os.getenv("TOKEN_JSON")
    if env_token:
        return json.loads(env_token)
    with open(FILE_PATH, 'r') as file:
        return json.load(file)

def get_response_token() -> str:
    data = read_dict_from_file()
    return data.get("refresh_token", "Token not found")

def get_access_token() -> str:
    data = read_dict_from_file()
    return data.get("access_token", "Token not found")

# Example usage
if __name__ == "__main__":
    response_token = get_response_token()
    print("Response Token:", response_token)

    access_token = get_access_token()
    print("Access Token:", access_token)
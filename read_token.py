import json

# Define the file path as a constant
FILE_PATH = "token.json"

def save_dict_to_file(data: dict) -> None:
    """
    Save a dictionary to a file in JSON format.
    """
    with open(FILE_PATH, 'w') as file:
        json.dump(data, file, indent=4)

def read_dict_from_file() -> dict:
    """
    Read a dictionary from a file in JSON format.
    """
    with open(FILE_PATH, 'r') as file:
        return json.load(file)

def get_response_token() -> str:
    """
    Extract the response token from the dictionary stored in the file.
    """
    data = read_dict_from_file()
    return data.get("refresh_token", "Token not found")

def get_access_token() -> str:
    """
    Extract the access token from the dictionary stored in the file.
    """
    data = read_dict_from_file()
    return data.get("access_token", "Token not found")

# Example usage
if __name__ == "__main__":
    # Read and extract the response token
    response_token = get_response_token()
    print("Response Token:", response_token)
    
    # Read and extract the access token
    access_token = get_access_token()
    print("Access Token:", access_token)
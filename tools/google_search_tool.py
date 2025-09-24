import os
from agents import function_tool
from serpapi import GoogleSearch

@function_tool
def google_search(query: str, num_results: int = 10) -> list[dict]:
    """
    Perform a Google search using the SerpAPI and return the results.

    Args:
        query (str): The search query string.
        num_results (int, optional): The number of search results to return. Defaults to 10.

    Returns:
        list[dict]: A list of dictionaries containing search result details such as title, link, and snippet.
    """
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise ValueError("SERPAPI_API_KEY environment variable is not set.")

    search = GoogleSearch({"q": query, "num": num_results, "api_key": api_key})
    results = search.get_dict()

    if "error" in results:
        raise RuntimeError(f"Error from SerpAPI: {results['error']}")

    return [
        {
            "title": result.get("title"),
            "link": result.get("link"),
            "snippet": result.get("snippet"),
        }
        for result in results.get("organic_results", [])
    ]

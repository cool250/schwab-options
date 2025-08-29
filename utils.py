from datetime import datetime


def convert_to_iso8601(date_string: str) -> str:
        """
        Convert a date string in 'YYYY-MM-DD' format to ISO 8601 format with milliseconds and UTC timezone.
        """
        dt = datetime.strptime(date_string, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%dT00:00:00.000Z")
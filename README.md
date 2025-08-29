# Schwab Options

Schwab Options is a Python-based project that interacts with the Schwab API to fetch account details, transactions, and other trading-related data. It uses `Pydantic` for data validation, `Loguru` for logging, and `python-dotenv` for managing environment variables.

---

## Features

- Fetch account hash values from the Schwab API.
- Retrieve and parse transactions for a given date range.
- Validate API responses using `Pydantic` models.
- Log detailed information about transactions and transfer items.

---

## Prerequisites

Before you begin, ensure you have the following installed:

- Python 3.8 or higher
- `pip` (Python package manager)

---

## Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-username/schwab-options.git
   cd schwab-options

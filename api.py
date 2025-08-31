from fastapi import FastAPI, HTTPException
from broker.accounts import AccountsTrading
from model.account_models import SecuritiesAccount

app = FastAPI()

# Initialize the AccountsTrading class
accounts_trading = AccountsTrading()

@app.get("/exposure")
def get_exposure():
    """
    Endpoint to fetch and return the total exposure for short PUT options.
    """
    securities_account = accounts_trading.get_positions()
    if not securities_account:
        raise HTTPException(status_code=404, detail="Securities account not found.")

    total_exposure = accounts_trading.calculate_total_exposure_for_short_puts(securities_account)
    return {"total_exposure": total_exposure}

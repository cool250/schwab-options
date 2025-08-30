from loguru import logger
from model.models import SecuritiesAccount

def log_transactions(transactions):
    """
    Log details of transactions represented as Pydantic objects.

    Args:
        transactions (List[Activity]): List of Activity Pydantic objects.
    """
    for transaction in transactions:
        logger.info(f"Transaction: {transaction.dict()}")  # Log the entire object as a dictionary

        # Log specific fields
        logger.info(f"Activity ID: {transaction.activityId}")
        logger.info(f"Account Number: {transaction.accountNumber}")
        logger.info(f"Type: {transaction.type}")
        logger.info(f"Status: {transaction.status}")
        logger.info(f"Net Amount: {transaction.netAmount}")

        # Log transfer items if available
        if transaction.transferItems:
            for item in transaction.transferItems:
                if item.instrument:
                    logger.info(f"  Instrument Symbol: {item.instrument.symbol}")
                    logger.info(f"  Instrument Description: {item.instrument.description}")
                logger.info(f"  Amount: {item.amount}")
                logger.info(f"  Cost: {item.cost}")
                logger.info(f"  Fee Type: {item.feeType}")
                logger.info(f"  Position Effect: {item.positionEffect}")

def log_securities_account(securities_account: SecuritiesAccount):
    """
    Log details of a SecuritiesAccount object, including nested data.

    Args:
        securities_account (SecuritiesAccount): The SecuritiesAccount object to log.
    """
    # Log top-level fields
    logger.info(f"Account Number: {securities_account.accountNumber}")
    logger.info(f"Round Trips: {securities_account.roundTrips}")
    logger.info(f"Is Day Trader: {securities_account.isDayTrader}")

    # Log initial balances if available
    if securities_account.initialBalances:
        logger.info("Initial Balances:")
        logger.info(f"  Cash Balance: {securities_account.initialBalances.cashBalance}")
        logger.info(f"  Equity: {securities_account.initialBalances.equity}")
        logger.info(f"  Margin Balance: {securities_account.initialBalances.marginBalance}")

    # Log current balances if available
    if securities_account.currentBalances:
        logger.info("Current Balances:")
        logger.info(f"  Equity: {securities_account.currentBalances.equity}")
        logger.info(f"  Margin Balance: {securities_account.currentBalances.marginBalance}")

    # Log positions if available
    if securities_account.positions:
        logger.info("Positions:")
        for position in securities_account.positions:
            logger.info(f"  Short Quantity: {position.shortQuantity}")
            logger.info(f"  Average Price: {position.averagePrice}")
            logger.info(f"  Current Day Profit/Loss: {position.currentDayProfitLoss}")
            logger.info(f"  Long Quantity: {position.longQuantity}")
            logger.info(f"  Market Value: {position.marketValue}")
            if position.instrument:
                logger.info("  Instrument:")
                logger.info(f"    CUSIP: {position.instrument.cusip}")
                logger.info(f"    Symbol: {position.instrument.symbol}")
                logger.info(f"    Description: {position.instrument.description}")
                logger.info(f"    Instrument ID: {position.instrument.instrumentId}")
                logger.info(f"    Net Change: {position.instrument.netChange}")
                logger.info(f"    Type: {position.instrument.type}")

def log_positions_with_short_quantity(securities_account: SecuritiesAccount):
    """
    Log positions where shortQuantity is greater than 0.

    Args:
        securities_account (SecuritiesAccount): The SecuritiesAccount object containing positions.
    """
    if not securities_account.positions:
        logger.info("No positions available to log.")
        return

    logger.info("Logging positions with shortQuantity > 0:")
    for position in securities_account.positions:
        if position.shortQuantity and position.shortQuantity > 0:
            logger.info(f"  Short Quantity: {position.shortQuantity}")
            logger.info(f"  Average Price: {position.averagePrice}")
            logger.info(f"  Current Day Profit/Loss: {position.currentDayProfitLoss}")
            logger.info(f"  Long Quantity: {position.longQuantity}")
            logger.info(f"  Market Value: {position.marketValue}")
            if position.instrument:
                logger.info("  Instrument:")
                logger.info(f"    CUSIP: {position.instrument.cusip}")
                logger.info(f"    Symbol: {position.instrument.symbol}")
                logger.info(f"    Description: {position.instrument.description}")
                logger.info(f"    Instrument ID: {position.instrument.instrumentId}")
                logger.info(f"    Net Change: {position.instrument.netChange}")
                logger.info(f"    Type: {position.instrument.type}")

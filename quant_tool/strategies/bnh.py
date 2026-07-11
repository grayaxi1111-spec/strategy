from quant_tool.strategies.base import Strategy, SignalType, Account

class BuyAndHoldStrategy(Strategy):
    """
    Buy and Hold (B&H) strategy.
    Simply generates a BUY signal whenever there is available cash, 
    and HOLDs forever (never sells).
    
    When used in a Portfolio with DCA enabled, this effectively becomes 
    a Dollar Cost Averaging (DCA) Buy & Hold strategy.
    """
    def generate_signal(self, row, account: Account) -> SignalType:
        # 只要有現金（足夠買至少一股，或我們簡化為只要有現金就送出 BUY，
        # 實際能買多少股由回測引擎的 execute_signal 根據當前 price 與成本決定）
        if account.cash > 0:
            return SignalType.BUY
        return SignalType.HOLD

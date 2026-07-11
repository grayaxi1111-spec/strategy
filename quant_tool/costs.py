import logging

import yaml

logger = logging.getLogger(__name__)

# 來回成本超過此比例即發出警告:策略 B(均值回歸)單筆只賺 1~3%,
# 0050 來回成本約 0.27% 會吃掉 10~30% 獲利(見 AGENTS.md 4.4 成本模型)。
HIGH_ROUND_TRIP_THRESHOLD = 0.002


class CostModel:
    """
    交易成本模型:把手續費、證交稅、滑價統一折算成「成交金額的比例」。

      買入現金流出 = 股數 × 價格 × (1 + buy_rate)
      賣出現金流入 = 股數 × 價格 × (1 - sell_rate)

    費率換算(from_config):
      TW(0050):buy_rate  = 手續費 0.1425% × 折扣
                sell_rate = 手續費 0.1425% × 折扣 + 證交稅 0.1%
      US(VOO) :buy_rate = sell_rate = 滑價 0.05%
    """

    def __init__(self, buy_rate: float = 0.0, sell_rate: float = 0.0, market: str = ""):
        self.buy_rate = float(buy_rate)
        self.sell_rate = float(sell_rate)
        self.market = market
        if self.round_trip_rate > HIGH_ROUND_TRIP_THRESHOLD:
            logger.warning(
                "%s 來回成本 %.4f%% 偏高:策略 B 單筆只賺 1~3%%,此成本會吃掉 10~30%% 獲利。"
                "建議策略 B 先只跑 VOO,0050 版本需回測確認淨期望值為正才啟用。",
                self.market or "此標的", self.round_trip_rate * 100,
            )

    @property
    def round_trip_rate(self) -> float:
        """買進 + 賣出一趟的總成本比例。"""
        return self.buy_rate + self.sell_rate

    def buy_cost(self, trade_value: float) -> float:
        """買入 trade_value(股數 × 價格)需額外支付的成本。"""
        return trade_value * self.buy_rate

    def sell_cost(self, trade_value: float) -> float:
        """賣出 trade_value(股數 × 價格)會被扣除的成本。"""
        return trade_value * self.sell_rate

    @classmethod
    def from_config(cls, costs_cfg: dict, market: str) -> "CostModel":
        """由 config 的 costs 區塊建立指定市場的成本模型(折扣比例可配置)。"""
        cfg = costs_cfg[market]
        discount = cfg.get("commission_discount", 1.0)
        buy_rate = (cfg.get("buy_commission_rate", 0.0) * discount
                    + cfg.get("buy_slippage", 0.0))
        sell_rate = (cfg.get("sell_commission_rate", 0.0) * discount
                     + cfg.get("sell_tax_rate", 0.0)
                     + cfg.get("sell_slippage", 0.0))
        return cls(buy_rate=buy_rate, sell_rate=sell_rate, market=market)

    @classmethod
    def from_yaml(cls, path: str, market: str) -> "CostModel":
        """直接從 config.yaml 讀取成本參數建立模型。"""
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return cls.from_config(config["costs"], market)

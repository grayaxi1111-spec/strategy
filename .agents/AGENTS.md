# Project Agent Rules
- 完成roadmap.md內容之後需要勾選
- 每次改動都要注意agents.md的架構需不需要改動

## Allowed Commands
- Agent may run all commands without asking for permission.
- Agent may read and write all files in this workspace without asking for permission.


# 專案目錄結構(現況)

> 開始任務前先看這裡定位檔案,不需要逐一讀完整個資料夾。
> 規劃中的完整骨架見下方第 5 節;此處只列「目前實際存在」的檔案。

```
strategy/
├── requirements.txt
├── .agents/
│   ├── AGENTS.md            # 本檔:agent 規則 + 系統架構文件
│   ├── ROADMAP.md           # 開發進度與待辦
│   └── git_commmit.md       # commit 訊息規範
├── quant_tool/              # 核心套件
│   ├── config.yaml          # 標的、成本、指標與策略參數
│   ├── data.py              # yfinance 下載 + SQLite 快取(還原股價)
│   ├── indicators.py        # 指標集中計算:SMA / 斜率 / RSI / SuperTrend
│   ├── backtest.py          # 單策略回測引擎(BacktestResult:trades + equity_curve)
│   ├── costs.py             # 成本模型:手續費/證交稅/滑價 → 統一費率,注入回測引擎
│   ├── metrics.py           # 績效層:CAGR/MDD/Sharpe/Sortino/勝率/盈虧比 + 組合層報表
│   └── strategies/
│       ├── base.py          # Strategy 抽象類別、SignalType、Account/Position
│       ├── trend.py         # 策略 A:趨勢跟蹤(MA 濾網 + SuperTrend 狀態機)
│       └── mean_rev.py      # 策略 B:均值回歸(RSI(2) 超賣反彈)
└── tests/                   # pytest,檔名與 quant_tool 模組一一對應
    ├── test_data.py
    ├── test_indicators.py
    ├── test_backtest.py
    ├── test_costs.py
    ├── test_metrics.py
    ├── test_trend.py
    └── test_mean_rev.py
```

尚未實作(見第 5 節骨架):`portfolio.py`(資金分配/再平衡)、`run.py`(入口)。

常用指令:測試跑 `.venv/bin/python -m pytest tests/`(pytest 裝在專案的 `.venv`,未啟用 venv 時直接打 `pytest` 會找不到指令)。


# 驗證方法(改動完成後如何端到端驗證)

純 library、尚無 CLI 入口(run.py 是 ROADMAP 第 11 節)。驗證面 = 套件公開介面,
用「run.py 將來的用法」寫一支駕駛腳本跑完整管線:
data → indicators → strategy → backtest(含成本) → metrics。

## 環境細節
- 駕駛腳本放專案外時要設 `PYTHONPATH=<專案根目錄>`
  (Python 只把腳本所在目錄加進模組路徑,不含 cwd)。

## 資料 fixture
- ⚠️ 不要用 `get_daily_data()` 拿驗證資料:首次下載 start=None 時 yfinance
  預設只抓 1 個月,且增量更新永不回填,還會在 `data/market_data.db` 留下
  永久卡短的快取(驗證完記得刪)。
- 改用 `yf.download('VOO', start='2015-01-01', auto_adjust=True)`,
  欄位照 data.py 規格轉小寫:date/open/high/low/close/volume,
  MultiIndex 欄位要先 `droplevel('Ticker')`。
- 策略暖機期 200 個交易日:資料至少要 300+ 根 K 才會有成交。

## 有效的交叉檢核(非循環論證)
1. **損益守恆(最強)**:策略期末空手時,`metrics.realized_trades()` 重放的
   已實現損益總和必須等於引擎的 `final_equity - initial_capital`
   (成本重放 vs 現金流,兩條獨立會計路徑)。
2. 期末仍持倉:已實現 + 未實現 = 淨值變化,
   剩餘持倉成本 = (本金 - 期末現金) + 已實現損益(注意是加號)。
3. MDD 用逐點迴圈重算,對 cummax 向量化版。
4. 合理性:策略 B 應高勝率(~0.75)低盈虧比(~0.4);
   兩策略 60 日滾動相關應在 0.3 附近。

## 值得重複的 probes
- 零交易帳本 → `summarize()` 不得崩,全部指標為 0
- 單點 equity 序列 → cagr/mdd/sharpe = 0
- 相關係數窗口 > 資料長度 → nan 不崩
- `CostModel.from_yaml(path, 'JP')` → 目前是裸 KeyError


# 量化交易系統架構 v1 — 趨勢 × 均值回歸雙引擎

標的:VOO / 0050(還原股價)
設計原則:兩個低相關子策略各自獨立運作,組合層負責資金分配與再平衡

---

## 0. 系統總覽

```
┌─────────────────────────────────────────────┐
│                Portfolio Layer               │
│   資金分配 50/50 · 季度再平衡 · 相關性監控      │
└──────────────┬───────────────┬──────────────┘
               │               │
   ┌───────────▼─────┐   ┌─────▼────────────┐
   │  Strategy A      │   │  Strategy B      │
   │  趨勢跟蹤         │   │  均值回歸         │
   │  MA濾網+SuperTrend│   │  RSI(2) 超賣反彈  │
   └───────────┬─────┘   └─────┬────────────┘
               │               │
┌──────────────▼───────────────▼──────────────┐
│              Shared Infrastructure           │
│  資料層 → 指標層 → 執行模型 → 成本模型 → 績效   │
└─────────────────────────────────────────────┘
```

三個指標的分工:
- **均線(MA20/60/200)** → 兩個策略共用的「環境濾網」
- **SuperTrend(10,3)** → 策略 A 的進出扳機
- **RSI(2)** → 策略 B 的進出扳機

---

## 1. Portfolio Layer(組合層)

```
capital_A = 總資金 × 50%   # 趨勢帳本
capital_B = 總資金 × 50%   # 均值回歸帳本

規則:
- 兩帳本獨立記帳、獨立持倉,互不知道對方存在
- 每季末再平衡回 50/50(賣賺的、補虧的)
- 定期定額現金流:每月入金按 50/50 分進兩個帳本的 cash_pool

監控指標:
- 兩帳本日報酬的滾動相關係數(60日),預期 < 0.3
- 若相關性長期 > 0.6,代表分散失效,需檢討
```

> 註:同一標的兩個帳本可能同時持有(趨勢滿倉 + 均值回歸進場),
> 實際下單時合併為淨部位即可,回測時分開記帳。

---

## 2. Strategy A — 趨勢跟蹤(細節見 strategy_pseudocode.md v1)

```
角色:賺大波段的錢,低勝率高盈虧比
頻率:日線(變體:週線/月線)

環境濾網: REGIME_BULL = MA20 > MA60 > MA200 且 MA200 斜率 ≥ -0.5%
持有許可: ALLOWED = REGIME_BULL AND SuperTrend == 綠

狀態機:  FLAT → FULL → HALF → (回補 FULL / 清倉 FLAT)
出場優先權 > 減碼 > 回補 > 進場
持有期:數週~數月
```

## 3. Strategy B — 均值回歸(RSI(2) 超賣反彈)

```
角色:賺盤整震盪的錢,高勝率低盈虧比
頻率:日線
持有期:2~10 個交易日

指標:
  RSI2  = RSI(close, 2)
  MA200 = SMA(close, 200)
  MA5   = SMA(close, 5)

環境濾網(防接刀,只在長多環境撿恐慌籌碼):
  close > MA200

進場(t 日收盤判斷,t+1 開盤執行):
  IF 空手 AND close > MA200 AND RSI2 < 10:
      BUY(投入本帳本可用資金)

  加碼(可選,scale-in):
  IF 已持倉 AND RSI2 < 5 AND 加碼次數 < 1:
      BUY 加碼一次(初始只投 50%,留 50% 給更深的超賣)

出場(先觸發先執行):
  1. IF RSI2 > 65 OR close > MA5:   獲利了結,全部賣出
  2. IF close < MA200:               環境破壞,無條件出場
  3. IF 持有天數 > 10:               時間停損,強制出場
     (超跌沒反彈 = 假設失效,不凹單)

注意:不設傳統的百分比停損。
均值回歸策略「越跌越該持有」,設價格停損會系統性地
在最差點位出場,歷史回測顯示反而傷害績效。
時間停損 + MA200 環境濾網就是它的風控。
```

## 4. Shared Infrastructure(共用基礎層)

```
4.1 資料層
  - yfinance 抓還原日線(auto_adjust=True)
  - VOO 直接抓;0050 用 "0050.TW"
  - 存本地 SQLite/CSV,增量更新,避免重複下載

4.2 指標層(集中計算,兩策略取用)
  - MA5 / MA20 / MA60 / MA200、SuperTrend(10,3)、RSI(2)、ADX(14)
  - 統一在收盤後計算一次,禁止盤中重算(避免未來函數)

4.3 執行模型
  - t 日收盤出訊號 → t+1 日開盤價成交
  - 暖機期 200 個交易日不交易

4.4 成本模型
  - 0050:買 0.1425%×折扣;賣 +0.1% 證交稅
  - VOO:買賣各 0.05% 滑價
  ⚠️ 關鍵警告:策略 B 單筆只賺 1~3%,0050 來回成本約 0.3%
     會吃掉 10~30% 的獲利。建議策略 B 先只跑 VOO,
     0050 版本回測後確認淨期望值仍為正才啟用。

4.5 績效層
  每個帳本 + 組合各出一份:
  CAGR / MDD / Sharpe / Sortino / 勝率 / 盈虧比 /
  年均交易次數 / time in market
  組合層額外輸出:兩帳本相關係數、再平衡貢獻
```

## 5. Python 模組結構(下一步實作的骨架)

```
quant_tool/
├── config.yaml          # 標的、成本、參數、資金分配
├── data.py              # 下載、快取、還原股價
├── indicators.py        # 所有指標集中計算
├── strategies/
│   ├── base.py          # Strategy 抽象類別(訊號介面統一)
│   ├── trend.py         # 策略 A:狀態機實作
│   └── mean_rev.py      # 策略 B:RSI(2)
├── portfolio.py         # 資金分配、再平衡、DCA 現金流
├── backtest.py          # 回測引擎(或包裝 backtesting.py)
├── metrics.py           # 績效計算與報表
└── run.py               # 入口:跑單策略 / 跑組合 / 跑變體矩陣
```

## 6. 回測矩陣(驗收順序)

```
Phase 1  基準線:純定期定額 B&H(VOO、0050 各一條)
Phase 2  策略 A 單獨(日線版 → 週線版)
Phase 3  策略 B 單獨(先 VOO,確認成本後測 0050)
Phase 4  A+B 組合 50/50 + 季度再平衡
Phase 5  敏感度測試:參數 ±20% 績效不能崩(防過擬合)
Phase 6  變體:槓桿版 / 債券輪動版 / ADX 濾網版

通過標準(相對 Phase 1 基準):
  組合 MDD 明顯更淺、Sharpe 更高,
  CAGR 不低於 B&H 的 85%,且 Phase 5 穩健
```

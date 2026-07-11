# 量化交易系統 Roadmap
> 依照 [AGENTS.md](AGENTS.md) 拆解，一個 Phase 完成所有開發與驗收。
> 做完一項就打 `[x]`。
---
## Phase 1: 完整系統開發與驗收
---
### 1. 專案初始化
- [x] 建立 `quant_tool/` 目錄結構
- [x] 建立 `quant_tool/__init__.py`
- [x] 建立 `config.yaml`：定義標的清單（VOO, 0050.TW）
- [x] `config.yaml`：定義成本參數（0050 手續費折扣、證交稅；VOO 滑價）
- [x] `config.yaml`：定義策略參數（MA 週期、SuperTrend 參數、RSI 週期）
- [x] `config.yaml`：定義資金分配比例（50/50）
- [x] `config.yaml`：定義再平衡頻率（每季）
- [x] `config.yaml`：定義暖機期天數（200）
- [x] 安裝相依套件（yfinance, pandas, numpy 等）並建立 `requirements.txt` ✅ venv 已建立於 `.venv/`
---
### 2. 資料層 (`data.py`)
- [x] 實作 yfinance 下載函數，支援 `auto_adjust=True`
- [x] 支援 VOO 直接下載
- [x] 支援 0050 用 `"0050.TW"` ticker 下載
- [x] 實作本地 SQLite 快取：首次下載完整資料
- [x] 實作增量更新：只下載上次更新日之後的新資料
- [x] 避免重複下載的防護邏輯
- [x] 提供統一的 `get_daily_data(ticker)` 介面回傳 DataFrame
- [x] 單元測試：驗證下載、快取、增量更新皆正常
---
### 3. 指標層 (`indicators.py`)
- [x] 實作 SMA(5) 計算
- [x] 實作 SMA(20) 計算
- [x] 實作 SMA(60) 計算
- [x] 實作 SMA(200) 計算
- [x] 實作 MA200 斜率計算（用於環境濾網判斷 ≥ -0.5%）
- [x] 實作 SuperTrend(10, 3) 計算（含 ATR、上下軌、方向判定）
- [x] 實作 RSI(2) 計算
- [x] 實作 ADX(14) 計算
- [x] 提供統一的 `compute_all_indicators(df)` 函數一次算完
- [x] 確保所有指標只用收盤後資料計算，無未來函數
- [x] 單元測試：用已知資料驗證每個指標的數值正確性
---
### 4. 策略基底類別 (`strategies/base.py`)
- [x] 定義 `Strategy` 抽象類別
- [x] 定義統一訊號介面：`generate_signal(row) → Signal`
- [x] 定義 Signal enum 或 dataclass（BUY / SELL / HOLD / REDUCE 等）
- [x] 定義帳本介面：持倉狀態、現金、部位查詢
- [x] 留好給子類別 override 的 hook
---
### 5. 策略 A — 趨勢跟蹤 (`strategies/trend.py`)
- [x] 實作環境濾網 `REGIME_BULL`：MA20 > MA60 > MA200
- [x] 實作環境濾網 `REGIME_BULL`：MA200 斜率 ≥ -0.5%
- [x] 實作持有許可 `ALLOWED`：REGIME_BULL AND SuperTrend == 綠
- [x] 實作狀態機 FLAT 狀態：等待進場
- [x] 實作狀態機 FLAT → FULL：ALLOWED 成立時全倉進場
- [x] 實作狀態機 FULL → HALF：SuperTrend 轉紅時減碼 50%
- [x] 實作狀態機 HALF → FULL：SuperTrend 再次轉綠且 REGIME_BULL 仍成立時回補
- [x] 實作狀態機 HALF → FLAT：REGIME_BULL 失效時清倉
- [x] 實作狀態機 FULL → FLAT：REGIME_BULL 失效時直接清倉
- [x] 實作出場優先權邏輯：出場 > 減碼 > 回補 > 進場
- [x] 單元測試：模擬各種狀態轉換情境
- [x] 單元測試：驗證訊號在暖機期內不觸發
---
### 6. 策略 B — 均值回歸 (`strategies/mean_rev.py`)
- [x] 實作環境濾網：close > MA200
- [x] 實作進場條件：空手 AND close > MA200 AND RSI2 < 10
- [x] 實作進場執行：t 日收盤判斷，t+1 開盤執行（策略層產生訊號，t+1 成交延遲已由第 7 節回測引擎 `backtest.py` 實作）
- [x] 實作加碼邏輯：已持倉 AND RSI2 < 5 AND 加碼次數 < 1
- [x] 實作初始倉位控制：初次只投 50%，留 50% 給加碼
- [x] 實作出場規則 1：RSI2 > 65 → 獲利了結全部賣出
- [x] 實作出場規則 2：close > MA5 → 獲利了結全部賣出
- [x] 實作出場規則 3：close < MA200 → 環境破壞無條件出場
- [x] 實作出場規則 4：持有天數 > 10 → 時間停損強制出場
- [x] 確認不設傳統百分比停損
- [x] 實作出場優先權：先觸發先執行
- [x] 追蹤持有天數計數器
- [x] 單元測試：模擬超賣進場 → 反彈出場流程
- [x] 單元測試：模擬環境破壞出場
- [x] 單元測試：模擬時間停損出場
---
### 7. 執行模型（回測引擎 `backtest.py`）
- [x] 實作 t 日收盤出訊號 → t+1 開盤成交的延遲邏輯
- [x] 實作暖機期 200 個交易日不交易的限制
- [x] 實作單策略回測迴圈：逐日跑策略 → 產生交易紀錄
- [x] 實作交易紀錄 DataFrame（日期、方向、價格、部位、現金）
- [x] 實作每日淨值計算（持倉市值 + 現金）
- [x] 單元測試：驗證延遲一日成交的正確性
- [x] 單元測試：驗證暖機期內無交易
---
### 8. 成本模型（獨立模組 `costs.py`，經 `cost_model` 參數注入 `backtest.py`）
- [x] 實作 0050 買入成本：手續費 0.1425% × 折扣
- [x] 實作 0050 賣出成本：手續費 0.1425% × 折扣 + 證交稅 0.1%
- [x] 實作 VOO 買入成本：滑價 0.05%
- [x] 實作 VOO 賣出成本：滑價 0.05%
- [x] 成本參數從 `config.yaml` 讀取，可配置折扣比例
- [x] 單元測試：驗證各標的來回成本計算正確
- [x] ⚠️ 記錄警告：策略 B 跑 0050 來回成本約 0.3%，會吃掉 10~30% 獲利（`costs.py` 於來回成本 > 0.2% 時發 `logger.warning`）
---
### 9. 績效層 (`metrics.py`)
- [x] 實作 CAGR（年化報酬率）計算
- [x] 實作 MDD（最大回撤）計算
- [x] 實作 Sharpe Ratio 計算
- [x] 實作 Sortino Ratio 計算
- [x] 實作勝率計算（獲利交易 / 總交易，由交易紀錄重放持倉成本計算已實現損益）
- [x] 實作盈虧比計算（平均獲利 / 平均虧損）
- [x] 實作年均交易次數計算
- [x] 實作 Time in Market 比例計算
- [x] 提供單一帳本的績效報表輸出（`summarize(BacktestResult)`）
- [x] 提供組合層的績效報表輸出（`portfolio_summary()`，吃 equity 曲線，由第 10 節 portfolio.py 調用）
- [x] 組合層額外：兩帳本滾動相關係數（60 日）
- [x] 組合層額外：再平衡貢獻分析（`rebalance_contribution()`，無再平衡 counterfactual 曲線由組合層提供）
- [x] 單元測試：用已知報酬序列驗證各指標數值
---
### 10. 組合層 (`portfolio.py`)
- [x] 實作雙帳本初始化：capital_A = 50%, capital_B = 50%
- [x] 實作兩帳本獨立記帳、獨立持倉
- [x] 實作季度再平衡邏輯：賣賺的、補虧的，回到 50/50
- [x] 實作 DCA 現金流：每月入金按 50/50 分進兩個帳本 cash_pool
- [x] 實作滾動相關係數監控（60 日窗口）
- [x] 實作相關性警告：長期 > 0.6 時輸出警告
- [x] 實作合併淨部位邏輯（同一標的兩帳本同時持有時）
- [x] 實作組合日淨值序列計算
- [x] 單元測試：驗證再平衡後資金比例正確
- [x] 單元測試：驗證 DCA 分配正確
---
### 11. 入口程式 (`run.py`)
- [x] 實作 CLI 參數解析（跑單策略 / 跑組合 / 跑變體矩陣）
- [x] 實作讀取 `config.yaml` 配置
- [x] 串接 data → indicators → strategy → backtest → metrics 完整流程
- [x] 實作結果輸出（console 表格 + CSV 匯出）
- [x] 實作權益曲線圖繪製
- [x] 端到端測試：用 VOO 資料跑完整流程確認不報錯
---
### 12. 回測矩陣驗收
- [x] 跑 Phase 1 基準線：VOO 純定期定額 B&H
- [x] 跑 Phase 1 基準線：0050 純定期定額 B&H
- [x] 跑 Phase 2：策略 A 單獨（日線版 VOO）
- [x] 跑 Phase 2：策略 A 單獨（日線版 0050）
- [x] 跑 Phase 2：策略 A 單獨（週線版 VOO）
- [x] 跑 Phase 3：策略 B 單獨（VOO）
- [x] 跑 Phase 3：策略 B 單獨（0050）— 確認淨期望值為正才啟用
- [x] 跑 Phase 4：A+B 組合 50/50 + 季度再平衡（VOO）
- [x] 跑 Phase 4：A+B 組合 50/50 + 季度再平衡（0050）
- [x] 跑 Phase 5：敏感度測試 — 各參數 ±20% 績效是否穩健
- [ ] 跑 Phase 6 變體：槓桿版 (待未來實作)
- [ ] 跑 Phase 6 變體：債券輪動版 (待未來實作)
- [ ] 跑 Phase 6 變體：ADX 濾網版 (待未來實作)
---
### 13. 驗收標準確認
- [x] 組合 MDD 明顯低於 B&H 基準
- [ ] 組合 Sharpe 高於 B&H 基準 (未通過)
- [ ] 組合 CAGR 不低於 B&H 的 85% (未通過)
- [x] Phase 5 敏感度測試通過（參數 ±20% 績效不崩）
- [ ] 兩帳本滾動相關係數 < 0.3（預期） (未通過，達到 1.00)
- [x] 策略 B 跑 0050 淨期望值確認（若為負則停用 0050）
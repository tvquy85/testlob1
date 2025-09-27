# 00_scope.md — Dự án HFT 1s (BTC/USDT & ETH/USDT, năm 2024)

**Vai trò:** Trưởng nhóm Quant  
**Mục tiêu cốt lõi:** Thiết kế — kiểm định — chuẩn hóa một chuỗi chiến lược giao dịch tần suất cao **khung 1 giây**, khai thác **Order Book 20 levels mỗi phía** kết hợp **OHLCV** và **bộ lọc đa khung (1m/5m/15m)** cho **BTC/USDT** và **ETH/USDT** trong **năm 2024**, có tính đến **chi phí, trễ, và rủi ro vi cấu trúc**.

---

## 1) Phạm vi (Scope) & Giới hạn (Out‑of‑scope)

**In‑scope**
- Thu thập/định chuẩn dữ liệu:  
  - LOB **20 mức bid/ask** với các cột: `origin_time`, `received_time`, `sequence_number`, `bid_[0..19]_{price,size}`, `ask_[0..19]_{price,size}`, `symbol`, `exchange`.  
  - OHLCV **1s** (tính/đồng bộ chỉ báo vi mô) và **1m** (làm bộ lọc 1m/5m/15m).
- Kỹ thuật đặc trưng vi cấu trúc: mid, spread, microprice, order‑book imbalance (OBI/OFI), queue imbalance, liquidity vacuum, micro‑momentum; hợp nhất đa khung.
- Thiết kế chiến lược: taker (breakout/micro‑reversion/liquidity vacuum) và maker (market making lệch/skew).  
- Backtester **event‑driven** mô phỏng fill/chi phí/slippage/latency; walk‑forward & CV theo tháng (purging/embargo).
- Đánh giá rủi ro overfitting (PBO), tail risk, regime shift; xuất báo cáo & TEARSHEET.

**Out‑of‑scope**
- Hạ tầng latency cực thấp (co‑location), tối ưu vi xử lý lệnh real‑time.  
- Giao dịch live/khuyến nghị đầu tư; triển khai production.  
- Sản phẩm khác ngoài BTC/USDT & ETH/USDT năm 2024; dữ liệu không thuộc bộ đã nêu.

---

## 2) Mục tiêu định lượng (Objectives)

- **Alpha khung 1s** sau chi phí (taker/maker) với bộ lọc đa khung (1m/5m/15m).  
- Tối thiểu:  
  - **Sharpe (test) > 1.0**, **Calmar > 0.5**, **Hit‑rate > 50%** (tùy chiến lược), **Turnover** phù hợp năng lực fill; **MaxDD** và **tail‑risk** nằm trong ngưỡng quản trị.  
  - **Khả năng chịu chi phí**: PnL dương ở nhiều cấu hình phí (taker_bps ∈ [5,10], maker_bps ∈ [1,5]) và **latency_ms** khác nhau.  
- **Ổn định theo tháng / theo symbol**; **PBO** ở mức chấp nhận được.

*(Ngưỡng trên là gợi ý để “gate” kết quả; quyết định cuối cùng dựa trên báo cáo TEARSHEET & PBO.)*

---

## 3) KPI & Chỉ số báo cáo

- **Hiệu quả**: CAGR, **Sharpe**, **Sortino**, **Calmar**, **t‑stat**, **Hit‑rate**, Profit per trade, Profit per second/minute.  
- **Rủi ro**: **MaxDD**, Tail‑risk (VaR/Expected Shortfall), Skew/Kurtosis, Intraday drawdown profile.  
- **Vận hành/chi phí**: **Turnover**, **Cost (bps)**, **Slippage** (mô hình), **Latency impact**.  
- **Độ tin cậy**: **PBO** (Probability of Backtest Overfitting) qua CSCV/walk‑forward; **stability by month/symbol**.

---

## 4) Dữ liệu & Hợp đồng dữ liệu (Data Contract)

- **Trục thời gian**:  
  - `origin_time` = mốc sự kiện (UTC), dùng cho đồng bộ & event engine.  
  - `received_time` = thời điểm nhận; dùng ước lượng **latency_ms = received − origin**.
- **LOB**: 20 mức mỗi phía; ràng buộc:  
  - `bid_0_price < ask_0_price`; `bid_i_price` giảm dần theo i; `ask_i_price` tăng dần; `size ≥ 0`.  
  - **spread ≥ 1 tick** (log ngoại lệ).  
- **OHLCV**: 1s (đồng bộ tín hiệu), 1m (lọc đa khung; suy rộng 5m/15m).  
- **Chuẩn hoá**: timezone = UTC; symbol nhất quán; đơn vị: **price = USDT**, **size = base asset**; `tick_size` suy luận từ dữ liệu/metadata.  
- **Liên kết**: join‑nearest theo `origin_time` (giới hạn lệch ≤ 500ms); resample 1s để tính feature.

---

## 5) Giả định chi phí & thực thi (Costs & Execution Model)

- **maker_bps**, **taker_bps** tham số hoá theo kịch bản;  
- **Slippage**: {none, proportional to top‑L depth, microprice shift};  
- **Latency_ms**: chèn trễ ra quyết định → giá/đặt lệnh;  
- **Funding/financing**: tham số hoá (nếu áp dụng theo sản phẩm sàn);  
- **Maker fill** (xấp xỉ do thiếu vị trí hàng đợi/prints): xác suất/khối lượng khớp tỉ lệ với **suy giảm size** quan sát tại top‑of‑book trong TTL, cho phép partial fill.

---

## 6) Rủi ro chính & Biện pháp giảm thiểu

- **Regime change** (biến động/liquidity khác nhau theo giai đoạn): phân tích theo tháng/quý; **walk‑forward**.  
- **Microstructure noise & sampling không đều**: dùng tính năng vi mô bền vững (OBI/OFI L‑levels, microprice), kiểm tra nhạy Δt.  
- **Overfitting/Leakage**: **CV theo tháng** với **purging** & **embargo**; **PBO** qua CSCV; kiểm tra out‑of‑sample.  
- **Chất lượng dữ liệu**: phát hiện gián đoạn, trùng/sai thứ tự ladder, spikes bất thường; **DQ report** trước khi backtest.  
- **Rủi ro vận hành**: circuit breaker theo intraday drawdown; giới hạn **max_positions**, **max_gross_exposure**.

---

## 7) Phương pháp luận nghiên cứu (Methodology)

- **Feature set** (ví dụ): mid, spread, microprice, microspread; **OBI/OFI** với L∈{1,3,5,10,20}; queue imbalance; liquidity vacuum; vi mô momentum (Δmid/Δmicroprice trong 250ms–1s); **bộ lọc 1m/5m/15m** (EMA, RV, regime).  
- **Nhãn mục tiêu**: future mid‑return {+1s,+2s,+3s} (regression & classification).  
- **Chiến lược**:  
  - **Taker**: OFI breakout; Microprice mean‑reversion; Liquidity‑vacuum.  
  - **Maker**: market making lệch (skew theo OBI/inventory), TTL ngắn.  
- **Tối ưu & đánh giá**: grid/random search có **purging/embargo**, chấm điểm theo KPI sau chi phí, kiểm **stability** & **PBO**.

---

## 8) Backtesting & Kiểm toán

- **Event‑driven** trên chuỗi snapshot (clock = `origin_time`), tính feature ở 1s nhưng **khớp theo sự kiện** giữa hai mốc.  
- **Taker fills**: tại `ask_0`/`bid_0` ± slippage; cộng phí taker.  
- **Maker fills**: xấp xỉ theo top‑of‑book depletion trong **TTL**; partial fills.  
- **Báo cáo**: trade log, equity curve, breakdown PnL theo ngày/giờ/spread regime, exposure, drawdown; **TEARSHEET HTML**.

---

## 9) Chuẩn đầu ra & Tổ chức Artefacts

- **Mỗi thử nghiệm** xuất:  
  - `config.yaml` (cấu hình run),  
  - `run.log` (nhật ký),  
  - `trades.csv` (thời gian/giá/khối lượng/phí/SL/TP),  
  - `metrics.json` (KPI chi tiết),  
  - `TEARSHEET.html` (báo cáo).  
- **Cấu trúc thư mục**: `runs/<run_id>/{config.yaml, run.log, trades.csv, metrics.json, TEARSHEET.html}`.  
- **Tái lập**: lưu `env.yml` (phiên bản thư viện), seed cố định, manifest dữ liệu.

---

## 10) Quản trị & Phiên bản (Governance)

- Quy ước đặt tên symbol/timeframe/partition (YYYY/MM/DD).  
- Kiểm soát thay đổi: PR review 2 lớp (Quant & Eng), tag phiên bản khi thay đổi data contract/chiến lược/backtester.  
- Nhật ký quyết định: `decision_note.md` sau mỗi chu kỳ chạy.

---

## 11) Checklist chất lượng dữ liệu (Data Quality)

1. **Tính hợp lệ LOB**  
   - `bid_0_price < ask_0_price`  
   - `bid_i_price` **giảm dần** theo i (i=0..19), `ask_i_price` **tăng dần** theo i  
   - `size ≥ 0` cho mọi mức; không NaN/Inf ở cột trọng yếu  
   - **spread ≥ 1 tick** (log ngoại lệ và tỷ lệ vi phạm)

2. **Tính toàn vẹn thời gian**  
   - `origin_time` tăng dần (không lùi thời gian); duplicate/giãn cách bất thường được log  
   - `received_time ≥ origin_time`; tính **latency_ms** và phân phối của nó  
   - Timezone **UTC** thống nhất

3. **Đồng bộ với OHLCV**  
   - Join‑nearest theo `origin_time` (|Δt| ≤ 500ms)  
   - Kiểm tra tỷ lệ snapshot không ghép được; xử lý thiếu/đột biến

4. **Nhất quán danh mục**  
   - `symbol`, `exchange` đồng nhất; không lẫn cặp sản phẩm  
   - Định danh phiên/phiên nghỉ (nếu có), cửa sổ “do_not_trade” cấu hình

5. **Kiểm tra thống kê**  
   - Phân phối spread, depth (L∈{1,3,5,10,20}), outlier detection  
   - Tỷ lệ vi phạm ladder; sự kiện gap/spike; missingblocks

> **Kết quả DQ**: sinh `dq_report.json` + biểu đồ tóm tắt trước khi cho phép chạy backtest.

---

## 12) Điều kiện bàn giao (Acceptance)

- Có ít nhất **01** chiến lược taker & **01** maker vượt ngưỡng KPI tối thiểu sau chi phí trên **test out‑of‑sample**;  
- **TEARSHEET** và **metrics.json** cho BTC & ETH; **PBO** tính toán rõ;  
- Kịch bản nhạy cảm phí/latency đạt PnL dương ở ≥ 2 cấu hình;  
- Tài liệu **data contract**, **features spec**, **strategy spec**, **backtester spec**, **runs config** hoàn chỉnh.

---

### Lưu ý & Tuân thủ
Nội dung mang tính kỹ thuật/nghiên cứu, **không phải** khuyến nghị đầu tư. Mọi thử nghiệm chỉ chạy trong môi trường backtest/paper‑trade; tuân thủ điều khoản sàn & quy định liên quan.


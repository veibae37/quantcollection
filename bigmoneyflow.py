"""
基于 AkShare 的盘后 ETF 资金护盘状态采集器 (本地直连版)

去除了原有的 HTTP API 依赖，直接通过 akshare 开源接口获取真实市场数据。
默认监测沪深 300 (510300) 和上证 50 (510050) 的极端放量护盘动作。

环境变量配置:
    NATIONAL_TEAM_ETFS
        需要监测的 ETF 列表，逗号分隔。默认: "510300,510050"
    QMT_REGIME_DIR
        状态文件输出目录。默认: C:\qmt_regime
    REGIME_RUN_TIME
        守护进程运行时间。默认: 15:35
"""

import argparse
import csv
import datetime
import json
import math
import os
import tempfile
import time
import akshare as ak
import pandas as pd

OUTPUT_FIELDS = [
    "trade_date",
    "regime",
    "direction",
    "total_net_flow_cny",
    "total_aum_cny",
    "flow_ratio_bps",
    "flow_zscore",
    "strength_score",
    "etf_count",
    "generated_at",
]

def fetch_etf_data_via_akshare(trade_date_iso, allowlist):
    """
    使用 AkShare 获取 ETF 数据，并构建护盘因子的特征输入。
    """
    # 将 YYYY-MM-DD 转换为 YYYYMMDD
    date_str = trade_date_iso.replace("-", "")
    normalized_records = []
    
    print(f"正在通过 AkShare 拉取 {trade_date_iso} 的行情数据...")
    
    # 获取全市场 ETF 最新概况（用于提取 AUM / 总市值）
    try:
        spot_df = ak.fund_etf_spot_em()
    except Exception as e:
        raise RuntimeError(f"获取 ETF 实时概况失败: {e}")

    for symbol in allowlist:
        # 剥离后缀，例如将 "510300.SH" 转换为 "510300"
        pure_code = symbol.split(".")[0] if "." in symbol else symbol
        
        try:
            # 获取单只 ETF 的历史日线数据
            hist_df = ak.fund_etf_hist_em(
                symbol=pure_code, 
                period="daily", 
                start_date=date_str, 
                end_date=date_str
            )
            
            if hist_df.empty:
                print(f"警告: {symbol} 在 {trade_date_iso} 无交易数据。")
                continue
                
            # 提取成交额作为护盘强度的 Proxy (代理指标)
            amount_cny = float(hist_df["成交额"].iloc[0])
            pct_change = float(hist_df["涨跌幅"].iloc[0])
            
            # 从 spot_df 中匹配总市值 (AUM)
            aum_cny = 0.0
            match_spot = spot_df[spot_df["代码"] == pure_code]
            if not match_spot.empty:
                aum_cny = float(match_spot["总市值"].iloc[0])
                
            # 资金流入量替代逻辑：
            # 国家队通常在下跌时托盘。如果当天收盘微跌或收红，但盘中爆出天量成交额，
            # 我们将这部分放量的“成交额”近似等效为“护盘净流入”。
            # 这里简单处理：将全部成交额视作流动性注入度量。
            proxy_inflow_cny = amount_cny
            
            normalized_records.append({
                "symbol": symbol,
                "net_inflow_cny": proxy_inflow_cny,
                "aum_cny": aum_cny
            })
            print(f"  > 成功拉取 {symbol} | 成交额: {proxy_inflow_cny/1e8:.2f}亿 | 涨跌幅: {pct_change}%")
            
        except Exception as e:
            print(f"拉取 {symbol} 数据时出错: {e}")
            continue

    if not normalized_records:
        raise ValueError("未能通过 AkShare 获取到任何有效的 ETF 数据。")

    return trade_date_iso, normalized_records, None

def load_history(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r") as handle:
        for row in csv.DictReader(handle):
            try:
                row["total_net_flow_cny"] = float(row["total_net_flow_cny"])
                rows.append(row)
            except Exception:
                continue
    rows.sort(key=lambda item: item["trade_date"])
    return rows

def flow_zscore(history, current_flow, lookback=60, min_history=20):
    values = [float(row["total_net_flow_cny"]) for row in history[-lookback:]]
    if len(values) < min_history:
        return 0.0, False
    mean = sum(values) / float(len(values))
    variance = sum((value - mean) ** 2 for value in values) / float(len(values))
    std = math.sqrt(variance)
    if std <= 0:
        return 0.0, True
    return (current_flow - mean) / std, True

def classify_regime(records, history, provider_strong, abs_flow_threshold, ratio_bps_threshold, zscore_threshold):
    total_flow = sum(item["net_inflow_cny"] for item in records)
    total_aum = sum(item["aum_cny"] for item in records)
    flow_ratio_bps = (total_flow / total_aum * 10000.0 if total_aum > 0 else 0.0)
    zscore, statistically_ready = flow_zscore(history, total_flow)

    magnitude_score = abs(total_flow) / max(abs_flow_threshold, 1.0)
    ratio_score = abs(flow_ratio_bps) / max(ratio_bps_threshold, 1.0)
    zscore_score = abs(zscore) / max(zscore_threshold, 0.01)
    strength_score = max(magnitude_score, ratio_score, zscore_score)

    magnitude_gate = abs(total_flow) >= abs_flow_threshold
    ratio_gate = total_aum > 0 and abs(flow_ratio_bps) >= ratio_bps_threshold
    statistical_gate = statistically_ready and abs(zscore) >= zscore_threshold

    if isinstance(provider_strong, bool):
        strong = provider_strong
    else:
        strong = ratio_gate or (magnitude_gate and (statistical_gate or not statistically_ready))

    direction = "INFLOW" if total_flow > 0 else "FLAT"

    return {
        "regime": "INTERVENTION" if strong else "NORMAL",
        "direction": direction,
        "total_net_flow_cny": total_flow,
        "total_aum_cny": total_aum,
        "flow_ratio_bps": flow_ratio_bps,
        "flow_zscore": zscore,
        "strength_score": strength_score,
        "etf_count": len(records),
    }

def atomic_write_json(path, data):
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    fd, temp_path = tempfile.mkstemp(prefix="regime_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except Exception:
            pass
        raise

def atomic_write_history(path, rows):
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    fd, temp_path = tempfile.mkstemp(prefix="regime_", suffix=".csv", dir=directory)
    try:
        with os.fdopen(fd, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELDS})
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except Exception:
            pass
        raise

def run_once(trade_date=None):
    trade_date = trade_date or datetime.date.today().isoformat()
    output_dir = os.environ.get("QMT_REGIME_DIR", r"C:\qmt_regime")
    
    # 默认监测 沪深300 和 上证50
    default_etfs = "510300.SH,510050.SH"
    allowlist = set(
        symbol.strip().upper()
        for symbol in os.environ.get("NATIONAL_TEAM_ETFS", default_etfs).split(",")
        if symbol.strip()
    )

    # 阈值设定：单日 50 亿成交额起步被视为异动，Z-score 偏离均值 2 倍标准差
    abs_flow_threshold = float(os.environ.get("REGIME_ABS_FLOW_THRESHOLD_CNY", "5000000000"))
    ratio_bps_threshold = float(os.environ.get("REGIME_FLOW_RATIO_BPS_THRESHOLD", "20"))
    zscore_threshold = float(os.environ.get("REGIME_ZSCORE_THRESHOLD", "2.0"))

    json_path = os.path.join(output_dir, "national_team_regime.json")
    history_path = os.path.join(output_dir, "national_team_regime_history.csv")
    
    history = [row for row in load_history(history_path) if row["trade_date"] != trade_date]

    # 直接调用 AkShare 数据源核心函数
    actual_date, records, provider_strong = fetch_etf_data_via_akshare(trade_date, allowlist)
    
    history = [row for row in history if row["trade_date"] != actual_date]
    metrics = classify_regime(records, history, provider_strong, abs_flow_threshold, ratio_bps_threshold, zscore_threshold)

    output = {
        "trade_date": actual_date,
        "generated_at": datetime.datetime.now().isoformat(),
        "regime": metrics["regime"],
        "direction": metrics["direction"],
        "total_net_flow_cny": metrics["total_net_flow_cny"],
        "total_aum_cny": metrics["total_aum_cny"],
        "flow_ratio_bps": metrics["flow_ratio_bps"],
        "flow_zscore": metrics["flow_zscore"],
        "strength_score": metrics["strength_score"],
        "etf_count": metrics["etf_count"],
        "symbols": [item["symbol"] for item in records],
    }

    history.append(output.copy())
    history.sort(key=lambda item: item["trade_date"])
    atomic_write_history(history_path, history)
    atomic_write_json(json_path, output)
    
    print("\n--- 判定结果 ---")
    print(json.dumps(output, sort_keys=True, ensure_ascii=False, indent=2))
    return output

def run_daemon():
    run_time = os.environ.get("REGIME_RUN_TIME", "15:35")
    last_run_date = None
    print(f"AkShare Collector 守护进程已启动; 设定的执行时间为每天 {run_time}")
    while True:
        now = datetime.datetime.now()
        today = now.date().isoformat()
        if (now.weekday() < 5 and now.strftime("%H:%M") >= run_time and last_run_date != today):
            try:
                run_once(today)
                last_run_date = today
            except Exception as exc:
                print(f"Collector error: {exc}")
        time.sleep(30)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--daemon", action="store_true", help="开启守护进程模式，每日盘后自动运行")
    args = parser.parse_args()
    
    if args.daemon:
        run_daemon()
    else:
        run_once(args.date)

if __name__ == "__main__":
    main()
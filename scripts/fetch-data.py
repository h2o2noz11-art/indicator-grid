#!/usr/bin/env python3
"""
data.json を無料APIから自動更新するスクリプト。

- 経済指標（NFP・CPI・FOMC実効金利・失業率・JOLTS）: FRED（無料・要APIキー）
  https://fred.stlouisfed.org/docs/api/api_key.html で無料登録して取得

GitHub Actions から1日1回実行される想定。
実行に必要な環境変数:
  FRED_API_KEY  ... FREDの無料APIキー
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "data.json")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def fred_series(series_id: str, limit: int = 14):
    """FREDから直近の観測値を新しい順で取得する。"""
    if not FRED_API_KEY:
        raise RuntimeError("環境変数 FRED_API_KEY が設定されていません。")
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(limit),
    }
    url = FRED_BASE + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as res:
        payload = json.load(res)
    obs = [o for o in payload.get("observations", []) if o.get("value") not in (".", None)]
    return obs  # 新しい順（obs[0]が最新）


def fmt_month(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.year}年{d.month}月分"


def build_nfp():
    # PAYEMS: 非農業部門雇用者数（水準、単位:千人）。前月差を計算する。
    obs = fred_series("PAYEMS", limit=4)
    # obs[0]=最新月, obs[1]=前月, obs[2]=前々月, obs[3]=3ヶ月前
    def diff_10k(i):
        latest = float(obs[i]["value"])
        prior = float(obs[i + 1]["value"])
        delta_thousands = latest - prior
        man = delta_thousands / 100.0  # 千人 → 万人
        sign = "+" if man >= 0 else "−"
        return f"{sign}{abs(man):.1f}万人", man

    curr_value, curr_man = diff_10k(0)
    prev_value, prev_man = diff_10k(1)

    return {
        "id": "nfp",
        "tag": "雇用",
        "name": "雇用統計（NFP）",
        "next": "次回発表日は米労働省の公式カレンダーを確認してください",
        "prev": {
            "date": f"{fmt_month(obs[2]['date'])}（速報)",
            "value": prev_value,
            "trend": "up" if prev_man > 0 else ("down" if prev_man < 0 else "flat"),
            "vs": "前月差（FRED自動計算）",
        },
        "curr": {
            "date": f"{fmt_month(obs[1]['date'])}（速報)",
            "value": curr_value,
            "trend": "up" if curr_man > 0 else ("down" if curr_man < 0 else "flat"),
            "vs": "前月差（FRED自動計算）",
        },
        "note": "FRED(PAYEMS)から自動計算した前月差です。市場予想との比較値は含まれないため、必要に応じて手動で補ってください。",
        "source": "FRED: PAYEMS",
    }


def build_cpi():
    # CPIAUCSL: 消費者物価指数（季節調整済み指数）。前年同月比を計算する。
    obs = fred_series("CPIAUCSL", limit=14)

    def yoy(i):
        latest = float(obs[i]["value"])
        year_ago = float(obs[i + 12]["value"])
        pct = (latest / year_ago - 1.0) * 100.0
        return f"{pct:+.1f}%", pct

    curr_value, curr_pct = yoy(0)
    prev_value, prev_pct = yoy(1)

    return {
        "id": "cpi",
        "tag": "物価",
        "name": "消費者物価指数（CPI）",
        "next": "次回発表日はBLSの公式カレンダーを確認してください",
        "prev": {
            "date": f"{fmt_month(obs[1]['date'])}",
            "value": prev_value,
            "trend": "flat",
            "vs": "前年同月比（FRED自動計算）",
        },
        "curr": {
            "date": f"{fmt_month(obs[0]['date'])}",
            "value": curr_value,
            "trend": "up" if curr_pct > prev_pct else ("down" if curr_pct < prev_pct else "flat"),
            "vs": "前年同月比（FRED自動計算）",
        },
        "note": "FRED(CPIAUCSL)から自動計算した前年同月比です。コア指数は別系列(CPILFESL)で取得できます。",
        "source": "FRED: CPIAUCSL",
    }


def build_fomc():
    # FEDFUNDS: 実効フェデラルファンド金利（月次）。FOMCの誘導目標そのものではない参考値。
    obs = fred_series("FEDFUNDS", limit=3)
    curr = obs[0]
    prev = obs[1]
    return {
        "id": "fomc",
        "tag": "金融政策",
        "name": "FOMC 政策金利（実効FF金利・参考値）",
        "next": "次回発表日はFRBの公式カレンダーを確認してください",
        "prev": {
            "date": f"{fmt_month(prev['date'])}",
            "value": f"{float(prev['value']):.2f}%",
            "trend": "flat",
            "vs": "実効金利（月中平均）",
        },
        "curr": {
            "date": f"{fmt_month(curr['date'])}",
            "value": f"{float(curr['value']):.2f}%",
            "trend": "up" if float(curr["value"]) > float(prev["value"]) else (
                "down" if float(curr["value"]) < float(prev["value"]) else "flat"
            ),
            "vs": "実効金利（月中平均）",
        },
        "note": "FEDFUNDSは実際の取引金利の月中平均であり、FOMCが発表する誘導目標レンジ（例:3.50-3.75%）とは異なる参考値です。",
        "source": "FRED: FEDFUNDS",
    }


def build_unrate():
    obs = fred_series("UNRATE", limit=3)
    curr = obs[0]
    prev = obs[1]
    curr_v = float(curr["value"])
    prev_v = float(prev["value"])
    return {
        "id": "unrate",
        "tag": "雇用",
        "name": "失業率",
        "next": "次回発表日はBLSの公式カレンダーを確認してください（NFPと同時発表）",
        "prev": {
            "date": f"{fmt_month(prev['date'])}",
            "value": f"{prev_v:.1f}%",
            "trend": "flat",
            "vs": "",
        },
        "curr": {
            "date": f"{fmt_month(curr['date'])}",
            "value": f"{curr_v:.1f}%",
            "trend": "down" if curr_v < prev_v else ("up" if curr_v > prev_v else "flat"),
            "vs": "低いほど良好",
        },
        "note": "FRED(UNRATE)から自動取得。",
        "source": "FRED: UNRATE",
    }


def build_jolts():
    # JTSJOL: 求人件数（単位:千件）
    obs = fred_series("JTSJOL", limit=3)
    curr = obs[0]
    prev = obs[1]

    def fmt(v):
        man = float(v) / 1000.0
        return f"{man:.1f}万件"

    curr_v = float(curr["value"])
    prev_v = float(prev["value"])
    return {
        "id": "jolts",
        "tag": "求人",
        "name": "JOLTS 求人件数",
        "next": "次回発表日はBLSの公式カレンダーを確認してください",
        "prev": {
            "date": f"{fmt_month(prev['date'])}",
            "value": fmt(prev["value"]),
            "trend": "flat",
            "vs": "",
        },
        "curr": {
            "date": f"{fmt_month(curr['date'])}",
            "value": fmt(curr["value"]),
            "trend": "down" if curr_v < prev_v else ("up" if curr_v > prev_v else "flat"),
            "vs": "",
        },
        "note": "FRED(JTSJOL)から自動取得。JOLTSはNFPより約1〜2ヶ月遅れて発表されます。",
        "source": "FRED: JTSJOL",
    }


def fetch_usdjpy():
    # frankfurter.app: 無料・APIキー不要・CORS対応（ECB基準レート）
    url = "https://api.frankfurter.app/latest?from=USD&to=JPY"
    with urllib.request.urlopen(url, timeout=20) as res:
        payload = json.load(res)
    return payload["rates"]["JPY"], payload["date"]


def fetch_gold():
    # goldprice.org の無料公開エンドポイント（APIキー不要）。非公式のため将来変更される可能性あり。
    url = "https://data-asg.goldprice.org/dbXRates/USD"
    with urllib.request.urlopen(url, timeout=20) as res:
        payload = json.load(res)
    item = payload["items"][0]
    return item["xauPrice"], payload.get("date")


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    by_id = {ind["id"]: ind for ind in data["indicators"]}

    try:
        by_id["nfp"] = build_nfp()
    except Exception as e:
        print(f"[warn] NFP更新に失敗: {e}", file=sys.stderr)

    try:
        by_id["cpi"] = build_cpi()
    except Exception as e:
        print(f"[warn] CPI更新に失敗: {e}", file=sys.stderr)

    try:
        by_id["fomc"] = build_fomc()
    except Exception as e:
        print(f"[warn] FOMC更新に失敗: {e}", file=sys.stderr)

    try:
        by_id["unrate"] = build_unrate()
    except Exception as e:
        print(f"[warn] 失業率更新に失敗: {e}", file=sys.stderr)

    try:
        by_id["jolts"] = build_jolts()
    except Exception as e:
        print(f"[warn] JOLTS更新に失敗: {e}", file=sys.stderr)

    data["indicators"] = list(by_id.values())

    try:
        usdjpy, jpy_date = fetch_usdjpy()
        data["market"]["usdjpy"] = {"price": round(usdjpy, 2), "as_of": jpy_date}
    except Exception as e:
        print(f"[warn] USD/JPY取得に失敗: {e}", file=sys.stderr)

    try:
        gold, gold_date = fetch_gold()
        data["market"]["gold_usd_oz"] = {"price": round(float(gold), 1), "as_of": gold_date}
    except Exception as e:
        print(f"[warn] 金価格取得に失敗: {e}", file=sys.stderr)

    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("data.json を更新しました。")


if __name__ == "__main__":
    main()

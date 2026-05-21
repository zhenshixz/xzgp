import os
import re
import sys
import time
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
from bs4 import BeautifulSoup
from curl_cffi import requests

# Ensure console output supports utf-8
sys.stdout.reconfigure(encoding='utf-8')

app = Flask(__name__, static_folder='../static')

def get_f10_code(code, quote_id):
    if not quote_id:
        return f"SH{code}" if code.startswith("6") else f"SZ{code}"
    if quote_id.startswith("1."):
        return f"SH{code}"
    elif quote_id.startswith("0."):
        return f"SZ{code}"
    elif quote_id.startswith("2."):
        return f"BJ{code}"
    else:
        return f"SH{code}" if code.startswith("6") else f"SZ{code}"

def parse_guba_date(date_str):
    """
    Parses date strings like '05-21 14:30' or '2025-05-21' into a datetime object.
    If the year is missing, infers it based on the current system time.
    """
    now = datetime.now()
    current_year = now.year
    
    date_str = date_str.strip()
    if not date_str:
        return None
        
    try:
        # Check if it has year already (e.g. YYYY-MM-DD or YYYY-MM-DD HH:MM)
        if len(date_str) >= 10 and date_str[4] == '-':
            # has year
            if ' ' in date_str:
                return datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            return datetime.strptime(date_str, "%Y-%m-%d")
        
        # Missing year (e.g. MM-DD HH:MM or MM-DD)
        if ' ' in date_str:
            parts = date_str.split(' ')
            md = parts[0].split('-')
            month, day = int(md[0]), int(md[1])
            hm = parts[1].split(':')
            hour, minute = int(hm[0]), int(hm[1])
        else:
            md = date_str.split('-')
            month, day = int(md[0]), int(md[1])
            hour, minute = 0, 0
            
        # Infer year: if the parsed month is greater than current month, it's likely from last year
        inferred_year = current_year
        if month > now.month or (month == now.month and day > now.day):
            inferred_year = current_year - 1
            
        return datetime(inferred_year, month, day, hour, minute)
    except Exception as e:
        print(f"Error parsing date string '{date_str}': {e}")
        return None

def fetch_guba_warnings(code):
    """
    Fetches news and announcements from Eastmoney Guba, filters for ST and delisting risk warning keywords
    published within the last 1 year.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    
    keywords = ["ST", "*ST", "退市", "风险警示", "终止上市", "特别处理", "限期整改", "暂停上市", "违规", "立案调查", "面值退市"]
    warnings = []
    
    now = datetime.now()
    one_year_ago = now.timestamp() - 365 * 86400
    
    # Check Tab 3 (Announcements) and Tab 1 (News)
    # Announcements contain official filings, News contains media disclosures
    for tab in [3, 1]:
        url = f"https://guba.eastmoney.com/list,{code},{tab},f.html"
        try:
            r = requests.get(url, headers=headers, impersonate="chrome", timeout=10)
            if r.status_code != 200:
                continue
                
            soup = BeautifulSoup(r.text, 'html.parser')
            trs = soup.find_all('tr', class_="listitem")
            for tr in trs:
                title_div = tr.find('div', class_="title")
                update_div = tr.find('div', class_="update")
                if not title_div or not update_div:
                    continue
                    
                a = title_div.find('a', href=True)
                if not a:
                    continue
                    
                title = a.get_text(strip=True)
                href = a['href']
                date_str = update_div.get_text(strip=True)
                
                pub_date = parse_guba_date(date_str)
                if not pub_date:
                    continue
                    
                # Check if it was published within 1 year
                if pub_date.timestamp() >= one_year_ago:
                    # Check if title contains warning keywords
                    match = any(kw.lower() in title.lower() for kw in keywords)
                    if match:
                        full_href = href if href.startswith("http") else "https://guba.eastmoney.com" + href
                        warnings.append({
                            "date": pub_date.strftime("%Y-%m-%d"),
                            "title": title,
                            "href": full_href,
                            "type": "公告" if tab == 3 else "资讯"
                        })
        except Exception as e:
            print(f"Error fetching Guba tab {tab} for {code}: {e}")
            
    # Sort warnings by date descending
    warnings.sort(key=lambda x: x["date"], reverse=True)
    return warnings

@app.route('/api/search')
def api_search():
    keyword = request.args.get('q', '').strip()
    if not keyword:
        return jsonify([])
        
    url = "https://searchapi.eastmoney.com/api/suggest/get"
    params = {
        "input": keyword,
        "type": "14", # Stocks
        "token": "D43BF722C8E33BDC906FB84D85E326E8",
        "count": "10"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    
    try:
        r = requests.get(url, params=params, headers=headers, impersonate="chrome", timeout=5)
        data = r.json()
        items = data.get("QuotationCodeTable", {}).get("Data", [])
        if not items:
            return jsonify([])
            
        results = []
        for item in items:
            results.append({
                "code": item.get("Code"),
                "name": item.get("Name"),
                "quote_id": item.get("QuoteID"),
                "security_typeName": item.get("SecurityTypeName")
            })
        return jsonify(results)
    except Exception as e:
        print("Search API error:", e)
        return jsonify([])

@app.route('/api/stock_info')
def api_stock_info():
    code = request.args.get('code', '').strip()
    quote_id = request.args.get('quote_id', '').strip()
    
    if not code:
        return jsonify({"success": False, "message": "股票代码不能为空"})
        
    f10_code = get_f10_code(code, quote_id)
    
    # 1. Fetch Fundamentals
    profile_url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={f10_code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/Index?type=web&code={f10_code}"
    }
    
    fundamentals = {}
    try:
        r = requests.get(profile_url, headers=headers, impersonate="chrome", timeout=10)
        profile_data = r.json()
        jbzl = profile_data.get("jbzl", {})
        fundamentals = {
            "name": jbzl.get("agjc", "--"),
            "full_name": jbzl.get("gsmc", "--"),
            "industry": jbzl.get("sshy", "--"),
            "legal_rep": jbzl.get("frdb", "--"),
            "chairman": jbzl.get("dsz", "--"),
            "reg_capital": jbzl.get("zczb", "--"),
            "exchange": jbzl.get("ssjys", "--"),
            "description": jbzl.get("gsjj", "--"),
            "scope": jbzl.get("jyfw", "--")
        }
    except Exception as e:
        print(f"Error fetching fundamentals for {code}: {e}")
        # Default fallback
        fundamentals = {
            "name": "--", "full_name": "--", "industry": "--", "legal_rep": "--",
            "chairman": "--", "reg_capital": "--", "exchange": "--", "description": "--", "scope": "--"
        }
        
    # 2. Fetch Profits from DataCenter
    profit_url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    profit_params = {
        "reportName": "RPT_DMSK_FN_INCOME",
        "columns": "ALL",
        "filter": f"(SECURITY_CODE=\"{code}\")",
        "pageNumber": "1",
        "pageSize": "40",  # Fetch last 40 entries to calculate YoY growth
        "sortTypes": "-1",
        "sortColumns": "REPORT_DATE",
        "source": "WEB",
        "client": "WEB"
    }
    
    yearly_profits = []
    quarterly_profits = []
    
    try:
        r_profit = requests.get(profit_url, params=profit_params, headers=headers, impersonate="chrome", timeout=10)
        profit_data = r_profit.json()
        if profit_data.get("success"):
            items = profit_data.get("result", {}).get("data", [])
            if items:
                # Parse dates and filter/sort in pure Python
                parsed_items = []
                for item in items:
                    report_date_str = item.get("REPORT_DATE")
                    if not report_date_str:
                        continue
                    date_part = report_date_str.split()[0]
                    try:
                        dt = datetime.strptime(date_part, "%Y-%m-%d")
                    except ValueError:
                        continue
                    
                    parsed_items.append({
                        "date": dt,
                        "year": dt.year,
                        "month": dt.month,
                        "PARENT_NETPROFIT": item.get("PARENT_NETPROFIT"),
                        "PARENT_NETPROFIT_RATIO": item.get("PARENT_NETPROFIT_RATIO")
                    })
                
                # Sort ascending by date
                parsed_items.sort(key=lambda x: x["date"])
                
                # Map for fast lookup by (year, month)
                lookup = {(x["year"], x["month"]): x for x in parsed_items}
                
                # A. Calculate single quarter profits
                for x in parsed_items:
                    year = x["year"]
                    month = x["month"]
                    cum_profit = x["PARENT_NETPROFIT"]
                    
                    if cum_profit is None:
                        x["Q_PARENT_NETPROFIT"] = None
                        continue
                        
                    if month == 3:
                        x["Q_PARENT_NETPROFIT"] = cum_profit
                    elif month in [6, 9, 12]:
                        prev_month = month - 3
                        prev_item = lookup.get((year, prev_month))
                        if prev_item is not None:
                            prev_cum_profit = prev_item["PARENT_NETPROFIT"]
                            if prev_cum_profit is not None:
                                x["Q_PARENT_NETPROFIT"] = cum_profit - prev_cum_profit
                            else:
                                x["Q_PARENT_NETPROFIT"] = None
                        else:
                            x["Q_PARENT_NETPROFIT"] = None
                    else:
                        x["Q_PARENT_NETPROFIT"] = None
                
                # B. Calculate single quarter YoY growth
                for x in parsed_items:
                    year = x["year"]
                    month = x["month"]
                    q_profit = x["Q_PARENT_NETPROFIT"]
                    
                    if q_profit is None:
                        x["Q_PARENT_NETPROFIT_YOY"] = None
                        continue
                        
                    prev_year_item = lookup.get((year - 1, month))
                    if prev_year_item is not None:
                        prev_q_profit = prev_year_item["Q_PARENT_NETPROFIT"]
                        if prev_q_profit is not None and prev_q_profit != 0:
                            yoy = (q_profit - prev_q_profit) / abs(prev_q_profit) * 100
                            x["Q_PARENT_NETPROFIT_YOY"] = yoy
                        else:
                            x["Q_PARENT_NETPROFIT_YOY"] = None
                    else:
                        x["Q_PARENT_NETPROFIT_YOY"] = None
                
                # C. Extract Yearly Profits (month = 12) for last 3 years
                yearly_items = [x for x in parsed_items if x["month"] == 12]
                selected_yearly = yearly_items[-3:][::-1]
                for x in selected_yearly:
                    date_str = x["date"].strftime("%Y-%m-%d")
                    profit = x["PARENT_NETPROFIT"]
                    yoy = x["PARENT_NETPROFIT_RATIO"]
                    yearly_profits.append({
                        "date": date_str,
                        "year": f"{x['year']}年",
                        "profit": float(profit) if profit is not None else None,
                        "profit_str": f"{profit/1e8:,.2f}亿" if profit is not None else "--",
                        "yoy": float(yoy) if yoy is not None else None,
                        "yoy_str": f"{yoy:+.2f}%" if yoy is not None else "--"
                    })
                    
                # D. Extract Quarterly Profits (last 4 quarters)
                quarterly_items = [x for x in parsed_items if x["Q_PARENT_NETPROFIT"] is not None]
                selected_quarterly = quarterly_items[-4:][::-1]
                for x in selected_quarterly:
                    date_str = x["date"].strftime("%Y-%m-%d")
                    q_profit = x["Q_PARENT_NETPROFIT"]
                    q_yoy_val = x["Q_PARENT_NETPROFIT_YOY"]
                    
                    quarter_names = {3: "一季度", 6: "二季度", 9: "三季度", 12: "四季度"}
                    q_name = f"{x['year']}年{quarter_names.get(x['month'], '季度')}"
                    
                    quarterly_profits.append({
                        "date": date_str,
                        "quarter": q_name,
                        "profit": float(q_profit) if q_profit is not None else None,
                        "profit_str": f"{q_profit/1e8:,.2f}亿" if q_profit is not None else "--",
                        "yoy": float(q_yoy_val) if q_yoy_val is not None else None,
                        "yoy_str": f"{q_yoy_val:+.2f}%" if q_yoy_val is not None else "--"
                    })
    except Exception as e:
        print(f"Error processing profits for {code}: {e}")
        
    # 2.5 Fetch concepts & K-line data
    if not quote_id:
        if code.startswith("6") or code.startswith("9"):
            secid = f"1.{code}"
        else:
            secid = f"0.{code}"
    else:
        secid = quote_id

    concepts = []
    try:
        concept_url = "https://push2.eastmoney.com/api/qt/slist/get"
        concept_params = {
            "forcect": "1",
            "spt": "3",
            "fields": "f1,f12,f152,f3,f14,f128,f136",
            "pi": "0",
            "pz": "1000",
            "po": "1",
            "fid": "f3",
            "fid0": "f4003",
            "invt": "2",
            "secid": secid
        }
        r_concept = requests.get(concept_url, params=concept_params, headers=headers, impersonate="chrome", timeout=5)
        concept_data = r_concept.json()
        diff = concept_data.get("data", {}).get("diff", {})
        if isinstance(diff, dict):
            for item in diff.values():
                name = item.get("f14")
                if name:
                    concepts.append(name)
    except Exception as e:
        print(f"Error fetching concepts for {code}: {e}")

    klines = []
    try:
        kline_url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        kline_params = {
            "secid": secid,
            "klt": "101",
            "fqt": "1",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "beg": "0",
            "end": "20500101",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b"
        }
        r_kline = requests.get(kline_url, params=kline_params, headers=headers, impersonate="chrome", timeout=5)
        kline_data = r_kline.json()
        raw_klines = kline_data.get("data", {}).get("klines", [])
        if raw_klines:
            for k in raw_klines[-60:]:
                parts = k.split(",")
                if len(parts) >= 6:
                    klines.append({
                        "date": parts[0],
                        "open": float(parts[1]),
                        "close": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "volume": float(parts[5])
                    })
    except Exception as e:
        print(f"Error fetching klines for {code}: {e}")

    # 3. Fetch Guba warnings (ST and delisting risk warning)
    warnings = fetch_guba_warnings(code)
    
    # 4. Assess overall risk level
    stock_name = fundamentals.get("name", "")
    is_already_st = "ST" in stock_name or "*ST" in stock_name or "退" in stock_name
    
    if is_already_st:
        risk_level = "Critical"
        risk_desc = "该股票已被实施ST、*ST风险警示或处于退市整理期，具有极高的退市风险！"
    elif len(warnings) > 0:
        if len(warnings) >= 3:
            risk_level = "High"
            risk_desc = f"近1年内发现 {len(warnings)} 条被实施ST或退市的警告风险资讯，退市或ST风险很高，请密切关注！"
        else:
            risk_level = "Medium"
            risk_desc = f"近1年内发现 {len(warnings)} 条包含ST或退市风险的警示公告或资讯，存在一定的潜在风险。"
    else:
        risk_level = "Low"
        risk_desc = "近1年内未在公司公告或资讯中发现明确的被ST或退市的风险警告，目前风险较低。"
        
    return jsonify({
        "success": True,
        "code": code,
        "f10_code": f10_code,
        "fundamentals": fundamentals,
        "yearly_profits": yearly_profits,
        "quarterly_profits": quarterly_profits,
        "warnings": warnings,
        "concepts": concepts,
        "klines": klines,
        "risk": {
            "level": risk_level,
            "description": risk_desc,
            "count": len(warnings)
        }
    })

@app.route('/')
def index():
    return send_from_directory('../static', 'index.html')

if __name__ == "__main__":
    os.makedirs('../static', exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)

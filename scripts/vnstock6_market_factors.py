"""FHSC/SSI auxiliary market factors for Gen6 with last-known-good caching."""
from __future__ import annotations
import math
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from typing import Any
import pandas as pd
from vnstock import Market

UTC=timezone.utc

def finite(value: Any) -> float | None:
    try:
        number=float(value)
        return number if math.isfinite(number) else None
    except (TypeError,ValueError): return None

def _records(frame: Any) -> list[dict[str,Any]]:
    if frame is None: return []
    if isinstance(frame,pd.DataFrame): return frame.reset_index().to_dict("records")
    if isinstance(frame,dict): return [frame]
    return list(frame) if isinstance(frame,list) else []

def _value(row: dict[str,Any],*names: str) -> Any:
    normalized={str(key).lower().replace(" ","_"):value for key,value in row.items()}
    for name in names:
        if name in normalized: return normalized[name]
    return None

def _sum(rows: list[dict[str,Any]],*names: str) -> float | None:
    values=[finite(_value(row,*names)) for row in rows]
    values=[value for value in values if value is not None]
    return sum(values) if values else None

def foreign_score(rows: list[dict[str,Any]]) -> tuple[float | None,dict[str,Any]]:
    if not rows: return None,{}
    latest=rows[-20:]; recent=latest[-5:]
    buy5=_sum(recent,"foreign_buy_value","buy_value","foreign_buy_val")
    sell5=_sum(recent,"foreign_sell_value","sell_value","foreign_sell_val")
    net5=_sum(recent,"net_value","foreign_net_value","net_val")
    if net5 is None and buy5 is not None and sell5 is not None: net5=buy5-sell5
    net20=_sum(latest,"net_value","foreign_net_value","net_val")
    if net20 is None:
        buy20=_sum(latest,"foreign_buy_value","buy_value","foreign_buy_val")
        sell20=_sum(latest,"foreign_sell_value","sell_value","foreign_sell_val")
        if buy20 is not None and sell20 is not None: net20=buy20-sell20
    if net5 is None: return None,{}
    turnover=abs(buy5 or 0)+abs(sell5 or 0)
    intensity=net5/turnover if turnover else 0
    raw=0
    if abs(intensity)>=.10:
        aligned=net20 is not None and (net20>0)==(net5>0)
        raw=(10 if abs(intensity)>=.30 and aligned else 5)*(1 if net5>0 else -1)
    score=round(max(-15,min(15,raw))/15*6)
    return score,{"foreign_net_5d":net5,"foreign_net_20d":net20,"foreign_intensity":intensity}

def proprietary_score(rows: list[dict[str,Any]]) -> tuple[float | None,dict[str,Any]]:
    if not rows: return None,{}
    nets=[]
    for row in rows[-20:]:
        net=finite(_value(row,"net_value","proprietary_net_value","net_val"))
        if net is None:
            buy=finite(_value(row,"buy_value","proprietary_buy_value")); sell=finite(_value(row,"sell_value","proprietary_sell_value"))
            net=buy-sell if buy is not None and sell is not None else None
        if net is not None: nets.append(net)
    if not nets: return None,{}
    n5=sum(nets[-5:])/1e9; n20=sum(nets)/1e9
    trend=(sum(nets[-5:])/5)-(sum(nets[-10:-5])/5) if len(nets)>=10 else 0
    raw=10 if n5>5 and n20>0 and trend>0 else 5 if n5>2 else 2 if n5>.5 else 0 if n5>-.5 else -2 if n5>-2 else -5 if n5>-5 else -10
    return round(raw/10*3),{"proprietary_net_5d":sum(nets[-5:]),"proprietary_net_20d":sum(nets)}

def insider_score(rows: list[dict[str,Any]]) -> tuple[float | None,dict[str,Any]]:
    if not rows: return None,{}
    buy=sell=0
    for row in rows:
        kind=str(_value(row,"transaction_type","deal_type","type") or "").lower()
        if any(word in kind for word in ("mua","buy","purchase","acqui")): buy+=1
        elif any(word in kind for word in ("bán","ban","sell","dispos")): sell+=1
    net=buy-sell
    raw=5 if net>=3 else 3 if net>=1 else 0 if net==0 else -3 if net>=-2 else -5
    return round(raw/5*2),{"insider_buy_count":buy,"insider_sell_count":sell}

def order_flow_score(rows: list[dict[str,Any]],snap_time: str) -> tuple[float | None,dict[str,Any]]:
    if not rows: return None,{}
    row=rows[-1]
    buy=finite(_value(row,"active_buy_volume","buy_volume")); sell=finite(_value(row,"active_sell_volume","sell_volume"))
    total=(buy or 0)+(sell or 0)
    if not total: return None,{}
    ratio=(buy-sell)/total
    score=4 if ratio>.35 else 2 if ratio>.15 else -4 if ratio<-.35 else -2 if ratio<-.15 else 0
    buy_count=finite(_value(row,"buy_order_count","active_buy_order_count")); sell_count=finite(_value(row,"sell_order_count","active_sell_order_count"))
    average_size=total/((buy_count or 0)+(sell_count or 0)) if (buy_count or 0)+(sell_count or 0)>0 else None
    return score,{"active_buy_volume":buy,"active_sell_volume":sell,"active_buy_order_count":buy_count,"active_sell_order_count":sell_count,"average_trade_size":average_size,"active_flow_ratio":ratio,"snap_time":snap_time}

def fetch_symbol(symbol: str,today: date,intraday: bool=True) -> dict[str,Any]:
    equity=Market("fhsc").equity(symbol)
    start20=(today-timedelta(days=35)).isoformat(); start90=(today-timedelta(days=100)).isoformat(); end=today.isoformat()
    result={"source":"FHSC","refreshed_at":datetime.now(UTC).isoformat(),"errors":{}}
    calls={"foreign":lambda:equity.foreign_flow(start=start20,end=end,interval="1D"),"proprietary":lambda:equity.proprietary_flow(start=start20,end=end),"insider":lambda:equity.insider_deal()}
    if intraday:
        calls["active_flow"]=lambda:equity.active_session()
        calls["order_book"]=lambda:equity.order_book()
    for name,call in calls.items():
        try: result[name]=_records(call())
        except Exception as exc: result["errors"][name]={"type":type(exc).__name__,"code":getattr(exc,"code",None),"action":getattr(exc,"action",None)}
    ff,ffraw=foreign_score(result.get("foreign",[])); prop,propraw=proprietary_score(result.get("proprietary",[])); insider,insraw=insider_score(result.get("insider",[])); of,ofraw=order_flow_score(result.get("active_flow",[]),datetime.now().strftime("%H:%M"))
    result.update({"s_ff_net":ff,"s_prop_5d":prop,"s_insider":insider,"s_of_phasefix":None,"s_depth_wall":None,"raw":{**ffraw,**propraw,**insraw,**ofraw,"order_book":result.get("order_book",[])}})
    result["endpoint_rows"]={name:len(result.get(name,[])) for name in calls}
    for name in calls: result.pop(name,None)
    return result
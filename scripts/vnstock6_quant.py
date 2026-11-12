"""Vnstock Quant calculations for the generation-6 production pipeline."""
from __future__ import annotations
import math
from typing import Any
import pandas as pd
from vnstock import Fundamental
from vnstock_quant import fa, ta

RATIO_IDS=("RT_PRT_ROE","RT_PRT_ROA","RT_PRT_GROSS_MARGIN","RT_PRT_NET_MARGIN","RT_LQD_CR","RT_LEV_DE")

def finite(value: Any) -> float | None:
    try:
        number=float(value)
        return number if math.isfinite(number) else None
    except (TypeError,ValueError):
        return None

def _last(value: Any) -> float | None:
    if isinstance(value,(pd.Series,pd.DataFrame)) and not value.empty:
        return finite(value.iloc[-1] if isinstance(value,pd.Series) else value.iloc[-1,-1])
    return finite(value)

def technical_indicators(frame: pd.DataFrame) -> dict[str,Any]:
    data=frame[["open","high","low","close","volume"]].copy()
    output={"engine":"vnstock_quant.ta","version":"1.0.0","errors":{}}
    specs={"ema20":("ema",{"length":20}),"ema50":("ema",{"length":50}),"ema200":("ema",{"length":200}),"rsi14":("rsi",{"length":14}),"atr14":("atr",{"length":14}),"obv":("obv",{})}
    for key,(name,params) in specs.items():
        try: output[key]=_last(ta.compute(data,name,**params))
        except Exception as exc:
            output[key]=None
            output["errors"][key]={"type":type(exc).__name__,"code":getattr(exc,"code",None),"action":getattr(exc,"action",None)}
    return output

def _clip(value: float) -> float:
    return max(-1.0,min(1.0,value))

def _growth(frames: list[pd.DataFrame], codes: tuple[str,...]) -> float | None:
    chunks=[]
    for frame in frames:
        column="line_code" if "line_code" in frame else "id" if "id" in frame else None
        if column and "period" in frame and "value" in frame:
            chunks.append(frame[frame[column].astype(str).isin(codes)][["period","value"]])
    if not chunks: return None
    values=pd.concat(chunks).drop_duplicates("period",keep="last").sort_values("period")
    values["value"]=pd.to_numeric(values["value"],errors="coerce")
    values=values.dropna()
    if len(values)<5: return None
    current,prior=finite(values.iloc[-1]["value"]),finite(values.iloc[-5]["value"])
    if current is None or prior in (None,0): return None
    return current/abs(prior)-(1 if prior>0 else -1)

def fundamental_factors(symbol: str, source: str) -> dict[str,Any]:
    frames=[]; statements={}
    try:
        equity=Fundamental(source).equity(symbol)
        for name in ("balance_sheet","income_statement","cash_flow"):
            frame=getattr(equity,name)(period="quarter",format="long",compat="v5")
            frames.append(frame)
            statements[name]={"status":"success","rows":len(frame),"schema_changes":list(frame.attrs.get("schema_changes",[])),"identities":frame.attrs.get("identities",[])}
        table=fa.ratios(fa.Dataset.from_frames({symbol:frames}),ids=list(RATIO_IDS),period="quarter",format="long")
        ratios={}
        if table is not None and not table.empty:
            table=table.sort_values("period")
            for ratio_id in RATIO_IDS:
                rows=table[table["id"]==ratio_id].copy()
                rows["value"]=pd.to_numeric(rows["value"],errors="coerce")
                rows=rows.dropna(subset=["value"])
                if not rows.empty: ratios[ratio_id]=float(rows.iloc[-1]["value"])
        parts=[]
        for key,center,scale,invert in (("RT_PRT_ROE",.08,.15,False),("RT_PRT_ROA",.03,.08,False),("RT_PRT_GROSS_MARGIN",.15,.25,False),("RT_PRT_NET_MARGIN",.05,.15,False),("RT_LQD_CR",1.,1.,False),("RT_LEV_DE",1.5,1.5,True)):
            if key in ratios: parts.append(_clip((center-ratios[key] if invert else ratios[key]-center)/scale))
        growth_values=[value for value in (_growth(frames,("IS_NET_REVENUE","IS_OPERATING_INCOME")),_growth(frames,("IS_NET_PROFIT_AFTER_TAX_OF_PARENT","IS_NET_PROFIT_AFTER_TAX"))) if value is not None]
        return {"fundamental":sum(parts)/len(parts) if parts else None,"growth":sum(_clip(v/.25) for v in growth_values)/len(growth_values) if growth_values else None,"fundamental_reason":None if parts else "vnstock_quant_no_usable_ratios","growth_reason":None if growth_values else "insufficient_quarterly_growth_history","ratios":ratios,"statements":statements,"engine":"vnstock_quant.fa","version":"1.0.0"}
    except Exception as exc:
        reason=getattr(exc,"code",None) or type(exc).__name__
        return {"fundamental":None,"growth":None,"fundamental_reason":reason,"growth_reason":reason,"ratios":{},"statements":statements,"engine":"vnstock_quant.fa","version":"1.0.0","error":{"type":type(exc).__name__,"code":getattr(exc,"code",None),"action":getattr(exc,"action",None)}}

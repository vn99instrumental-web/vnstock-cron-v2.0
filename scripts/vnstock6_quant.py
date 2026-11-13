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

def _wilder_adx_supertrend(data: pd.DataFrame, length: int = 14, st_length: int = 10, multiplier: float = 3.0) -> tuple[float | None,float | None]:
    high=pd.to_numeric(data["high"],errors="coerce"); low=pd.to_numeric(data["low"],errors="coerce"); close=pd.to_numeric(data["close"],errors="coerce")
    previous=close.shift(1); tr=pd.concat(((high-low).abs(),(high-previous).abs(),(low-previous).abs()),axis=1).max(axis=1)
    up=high.diff(); down=-low.diff(); plus_dm=up.where((up>down)&(up>0),0.0); minus_dm=down.where((down>up)&(down>0),0.0)
    atr=tr.ewm(alpha=1/length,adjust=False,min_periods=length).mean(); plus_di=100*plus_dm.ewm(alpha=1/length,adjust=False,min_periods=length).mean()/atr; minus_di=100*minus_dm.ewm(alpha=1/length,adjust=False,min_periods=length).mean()/atr
    dx=100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,float("nan")); adx=finite(dx.ewm(alpha=1/length,adjust=False,min_periods=length).mean().iloc[-1])
    st_atr=tr.ewm(alpha=1/st_length,adjust=False,min_periods=st_length).mean(); middle=(high+low)/2; upper=(middle+multiplier*st_atr).copy(); lower=(middle-multiplier*st_atr).copy(); trend=pd.Series(index=data.index,dtype=float)
    for i in range(1,len(data)):
        if pd.notna(upper.iloc[i-1]) and close.iloc[i-1]<=upper.iloc[i-1]: upper.iloc[i]=min(upper.iloc[i],upper.iloc[i-1])
        if pd.notna(lower.iloc[i-1]) and close.iloc[i-1]>=lower.iloc[i-1]: lower.iloc[i]=max(lower.iloc[i],lower.iloc[i-1])
        prior=trend.iloc[i-1]
        if pd.isna(prior): trend.iloc[i]=lower.iloc[i] if close.iloc[i]>=middle.iloc[i] else upper.iloc[i]
        elif prior==upper.iloc[i-1]: trend.iloc[i]=lower.iloc[i] if close.iloc[i]>upper.iloc[i] else upper.iloc[i]
        else: trend.iloc[i]=upper.iloc[i] if close.iloc[i]<lower.iloc[i] else lower.iloc[i]
    return adx,finite(trend.iloc[-1])
def technical_indicators(frame: pd.DataFrame) -> dict[str,Any]:
    data=frame[["open","high","low","close","volume"]].copy()
    output={"engine":"vnstock_quant.ta","version":"1.0.0","errors":{}}
    specs={"ema20":("ema",{"length":20}),"ema50":("ema",{"length":50}),"ema200":("ema",{"length":200}),"rsi14":("rsi",{"length":14}),"atr14":("atr",{"length":14}),"obv":("obv",{})}
    for key,(name,params) in specs.items():
        try: output[key]=_last(ta.compute(data,name,**params))
        except Exception as exc:
            output[key]=None
            output["errors"][key]={"type":type(exc).__name__,"code":getattr(exc,"code",None),"action":getattr(exc,"action",None)}
    output["adx14"],output["supertrend"]=_wilder_adx_supertrend(data)
    output["derived_engine"]="local_wilder_reference"
    return output

def _clip(value: float) -> float:
    return max(-1.0,min(1.0,value))

def _growth(frames: list[pd.DataFrame], codes: tuple[str,...]) -> float | None:
    chunks=[]
    for frame in frames:
        column="id" if "id" in frame else "line_code" if "line_code" in frame else None        if column and "period" in frame and "value" in frame:
            chunks.append(frame[frame[column].astype(str).isin(codes)][["period","value"]])
    if not chunks: return None
    values=pd.concat(chunks).drop_duplicates("period",keep="last").sort_values("period")
    values["value"]=pd.to_numeric(values["value"],errors="coerce")
    values=values.dropna()
    if len(values)<5: return None
    current,prior=finite(values.iloc[-1]["value"]),finite(values.iloc[-5]["value"])
    if current is None or prior in (None,0): return None
    return current/abs(prior)-(1 if prior>0 else -1)

def fundamental_factors(symbol: str, source: str, industry: str | None = None) -> dict[str,Any]:
    frames=[]; statements={}
    try:
        equity=Fundamental(source).equity(symbol)
        for name in ("balance_sheet","income_statement","cash_flow"):
            frame=getattr(equity,name)(period="quarter",format="long",compat="v5")
            frames.append(frame)
            statements[name]={"status":"success","rows":len(frame),"schema_changes":list(frame.attrs.get("schema_changes",[])),"identity_issue_count":len(frame.attrs.get("identities",[]))}
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
        cash=frames[2] if len(frames)>2 else pd.DataFrame(); income=frames[1] if len(frames)>1 else pd.DataFrame()
        def latest_line(frame,codes):
            column="id" if "id" in frame else "line_code" if "line_code" in frame else None
            if not column or "value" not in frame: return None
            rows=frame[frame[column].astype(str).isin(codes)].copy()
            if "period" in rows: rows=rows.sort_values("period")
            values=pd.to_numeric(rows.get("value"),errors="coerce").dropna(); return finite(values.iloc[-1]) if not values.empty else None
        cfo=latest_line(cash,("CF_CASH_FLOW_FROM_OPERATING_ACTIVITIES","CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES","CF_OPERATING")); net_profit=latest_line(income,("IS_NET_PROFIT_AFTER_TAX_OF_PARENT","IS_NET_PROFIT_AFTER_TAX")); cf_quality=finite(cfo/net_profit) if cfo is not None and net_profit not in (None,0) else None
        sector=unicodedata.normalize("NFKD",str(industry or "")).encode("ascii","ignore").decode().lower(); financial=any(term in sector for term in ("ngan hang","chung khoan","bao hiem","bank","securities","insurance")); cf_parts=[]
        if industry and not financial and cfo is not None: cf_parts.append(5 if cfo>0 else -10)
        if industry and not financial and cf_quality is not None: cf_parts.append(5 if cf_quality>1 else -5 if cf_quality<.5 else 0)
        cf_score=max(-10,min(10,sum(cf_parts))) if cf_parts else None
        return {"fundamental":sum(parts)/len(parts) if parts else None,"growth":sum(_clip(v/.25) for v in growth_values)/len(growth_values) if growth_values else None,"cash_flow":None if cf_score is None else cf_score/10,"cash_flow_score":cf_score,"cash_flow_operating":cfo,"cash_flow_quality":cf_quality,"industry":industry,"fundamental_reason":None if parts else "vnstock_quant_no_usable_ratios","growth_reason":None if growth_values else "insufficient_quarterly_growth_history","cash_flow_reason":None if cf_score is not None else "sector_cash_flow_excluded" if financial else "industry_unavailable" if not industry else "vnstock_quant_no_usable_cash_flow","ratios":ratios,"statements":statements,"engine":"vnstock_quant.fa","version":"1.1.0"}
    except Exception as exc:
        reason=getattr(exc,"code",None) or type(exc).__name__
        return {"fundamental":None,"growth":None,"cash_flow":None,"fundamental_reason":reason,"growth_reason":reason,"cash_flow_reason":reason,"ratios":{},"statements":statements,"engine":"vnstock_quant.fa","version":"1.1.0","error":{"type":type(exc).__name__,"code":getattr(exc,"code",None),"action":getattr(exc,"action",None)}}

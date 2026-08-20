/* VNINDEX live header — nạp bởi indexv4.html / indexv2.html (GitHub Pages).
   Đọc output/vnindex_live.json (raw GitHub, luôn bản mới nhất), render:
   - V4: cập nhật #vniClose/#vniChgs (thay số hôm qua bằng live + Δ điểm/Δ%).
   - V2.3 (không header): tự chèn banner #vniLive lên đầu body.
   Fail-soft: raw lỗi/thiếu file → giữ nguyên trang. */
(function () {
  var RAW = "https://raw.githubusercontent.com/vn99instrumental-web/vnstock-cron-v2.0/main/output/vnindex_live.json";
  function f(n, d) {
    return (n == null || isNaN(n)) ? "\u2014"
      : Number(n).toLocaleString("vi-VN", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function pc(n) { return (n == null || isNaN(n)) ? "" : ((n >= 0 ? "+" : "") + f(n, 2) + "%"); }
  function paint(v) {
    if (!v) return;
    var up = (v.chg_abs || 0) >= 0, col = up ? "#34c26e" : "#e86030", s = up ? "+" : "";
    var lvl = f(v.level, 2);
    var da = (v.chg_abs == null) ? "" : (s + f(v.chg_abs, 2) + " \u0111");   // đ
    var dp = (v.chg_pct == null) ? "" : ("(" + s + f(v.chg_pct, 2) + "%)");
    var tag = v.is_live
      ? ("trong phi\u00ean \u00b7 c\u1eadp nh\u1eadt " + (v.snap_time || ""))
      : ((v.asof_date || "") + " \u00b7 \u0111\u00e3 ch\u1ed1t/phi\u00ean tr\u01b0\u1edbc");
    var ex = "";
    if (v.ret_5d != null || v.ret_20d != null) {
      ex = ' <span style="opacity:.7">\u00b7 5D ' + pc(v.ret_5d) + ' \u00b7 20D ' + pc(v.ret_20d) + '</span>';
    }
    // V4 header (nếu có)
    var c = document.getElementById("vniClose");
    if (c) { c.textContent = lvl; c.style.color = col; }
    var ch = document.getElementById("vniChgs");
    if (ch) {
      ch.innerHTML = '<b style="color:' + col + '">' + da + ' ' + dp + '</b> vs phi\u00ean tr\u01b0\u1edbc'
        + ex + ' \u00b7 <span style="opacity:.8">' + tag + '</span>';
    }
    // Banner chung (mọi dashboard)
    var b = document.getElementById("vniLive");
    if (!b) {
      b = document.createElement("div"); b.id = "vniLive";
      b.style.cssText = "margin:0 0 10px;padding:8px 12px;border-radius:10px;"
        + "background:rgba(20,184,212,.08);border:1px solid rgba(20,184,212,.35);"
        + "font-size:13px;display:flex;gap:12px;align-items:center;flex-wrap:wrap";
      document.body.insertBefore(b, document.body.firstChild);
    }
    b.innerHTML = '\ud83c\udf0f <b>VNINDEX</b> <b style="font-size:16px">' + lvl + '</b> '
      + '<span style="color:' + col + ';font-weight:700">' + da + ' ' + dp + '</span> '
      + '<span style="opacity:.75">vs phi\u00ean tr\u01b0\u1edbc \u00b7 ' + tag + '</span>' + ex;
  }
  try {
    fetch(RAW + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(paint).catch(function () {});
  } catch (e) {}
})();

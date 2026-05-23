from vnstock_news import SITES_CONFIG
for site, cfg in SITES_CONFIG.items():
    has_rss = bool(cfg.get('rss_urls') or cfg.get('rss') or cfg.get('feed_url'))
    print(f"{site:<30} RSS={has_rss}")

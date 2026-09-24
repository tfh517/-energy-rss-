# -*- coding: utf-8 -*-
"""
源定义。想加源 / 删源 / 改标题，只动这个文件就够了。

kind 取值含义:
  nea  -- 国家能源局那套「新华云」页面: 列表页是 JS 渲染的,
          但页面里藏着数据源 ID, 顺着它就能拿到公开的 JSON 列表。
  csg  -- 南方电网官网的静态列表页, 直接解析 <span>日期</span><h2><a>标题</a></h2>。
  bjx  -- 北极星电力网, 解析页面里的 /html/YYYYMMDD/数字.shtml 文章链接,
          日期直接从链接路径里取。
  cnki -- 知网的老式 RSS。这个源本身是好的, 是 Inoreader 的抓取服务器被拦,
          所以我们自己取回来、重新封装成干净的 RSS 再给它。
"""

SOURCES = [
    # ---------------- 国家能源局 ----------------
    {
        "id": "nea-tongzhi",
        "group": "国家能源局",
        "title": "国家能源局 · 通知",
        "kind": "nea",
        "page": "https://www.nea.gov.cn/policy/tz.htm",
        "site": "https://www.nea.gov.cn/policy/tz.htm",
        "desc": "国家能源局「通知」栏目, 含行业标准制修订计划等文件。",
    },
    {
        "id": "nea-gonggao",
        "group": "国家能源局",
        "title": "国家能源局 · 公告",
        "kind": "nea",
        "page": "https://www.nea.gov.cn/policy/gg.htm",
        "site": "https://www.nea.gov.cn/policy/gg.htm",
        "desc": "国家能源局「公告」栏目, 含新能源建档立卡、数据发布等。",
    },
    {
        "id": "nea-yaowen",
        "group": "国家能源局",
        "title": "国家能源局 · 能源要闻",
        "kind": "nea",
        "page": "https://www.nea.gov.cn/xwzx/nyyw.htm",
        "site": "https://www.nea.gov.cn/xwzx/nyyw.htm",
        "desc": "国家能源局「能源要闻」, 条目自带摘要, 适合快速浏览。",
    },

    # ---------------- 学术期刊 ----------------
    {
        "id": "zgdc",
        "group": "学术期刊",
        "title": "中国电机工程学报 · 最新目录",
        "kind": "cnki",
        "url": "http://rss.cnki.net/grid20/rss.aspx?Journal=ZGDC&Virtual=grid20",
        "site": "http://ntps.epri.sgcc.com.cn/djgcxb/CN/home",
        "desc": "知网 RSS 取回后重新封装。含标题、作者、摘要, 随网络首发滚动更新。",
    },
    {
        "id": "dwjs",
        "group": "学术期刊",
        "title": "电网技术 · 最新目录",
        "kind": "cnki",
        "url": "http://rss.cnki.net/grid20/rss.aspx?Journal=DWJS&Virtual=grid20",
        "site": "http://rss.cnki.net/grid20/rss.aspx?Journal=DWJS&Virtual=grid20",
        "desc": "知网 RSS 取回后重新封装。注意 www.dwjs.com.cn 这个官网域名已经解析不出来, 别再用。",
    },

    # ---------------- 南方电网 ----------------
    {
        "id": "csg-yaowen",
        "group": "南方电网",
        "title": "南方电网 · 公司要闻",
        "kind": "csg",
        "page_tpl": "https://www.csg.cn/xwzx/{y}/{y}gsyw/",
        "site": "https://www.csg.cn/xwzx/",
        "desc": "南方电网官网「公司要闻」, 可替代公众号「南网50Hz」的官方口径内容。",
    },
    {
        "id": "csg-yixian",
        "group": "南方电网",
        "title": "南方电网 · 一线传真",
        "kind": "csg",
        "page_tpl": "https://www.csg.cn/xwzx/{y}/{y}yxcz/",
        "site": "https://www.csg.cn/xwzx/",
        "desc": "南方电网官网「一线传真」, 偏基层、工程现场与具体实践。",
    },
    {
        "id": "csg-meiti",
        "group": "南方电网",
        "title": "南方电网 · 媒体关注",
        "kind": "csg",
        "page_tpl": "https://www.csg.cn/xwzx/{y}/{y}mtgz/",
        "site": "https://www.csg.cn/xwzx/",
        "desc": "人民日报、央视、新华社等媒体对南方电网的报道汇总。",
    },

    # ---------------- 北极星电力网 ----------------
    {
        "id": "bjx-shupeidian",
        "group": "北极星电力网",
        "title": "北极星 · 输配电",
        "kind": "bjx",
        "page": "https://shupeidian.bjx.com.cn/",
        "site": "https://shupeidian.bjx.com.cn/",
        "desc": "北极星输配电频道。电网侧政策、招标、工程动态。",
    },
    {
        "id": "bjx-yaowen",
        "group": "北极星电力网",
        "title": "北极星 · 综合要闻",
        "kind": "bjx",
        "page": "https://www.bjx.com.cn/",
        "site": "https://www.bjx.com.cn/",
        "desc": "北极星首页当日要闻汇总。条目多、更新快, 适合当行业雷达。",
    },

    # ---------------- 想扩展的话, 照着上面抄一份 ----------------
    # 北极星各频道基本都能用 kind="bjx" 直接加, 例如:
    # {
    #     "id": "bjx-chuneng",
    #     "group": "北极星电力网",
    #     "title": "北极星 · 储能",
    #     "kind": "bjx",
    #     "page": "https://chuneng.bjx.com.cn/",
    #     "site": "https://chuneng.bjx.com.cn/",
    #     "desc": "储能频道。",
    # },
]

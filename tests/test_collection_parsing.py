"""采集源格式解析回归测试。"""

from controller.dc_controller import _parse_content


def test_rss_parser_returns_one_record_per_item():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel>
      <item><title>第一条</title><link>https://example.com/1</link><description><![CDATA[<p>第一条正文</p>]]></description></item>
      <item><title>第二条</title><link>/2</link><description>第二条正文</description></item>
    </channel></rss>"""
    rows = _parse_content(xml, "rss", "item", "https://example.com/feed")
    assert rows == [
        {"title": "第一条", "content": "第一条正文", "url": "https://example.com/1"},
        {"title": "第二条", "content": "第二条正文", "url": "https://example.com/2"},
    ]


def test_selector_parser_resolves_anchor_and_nested_links():
    html = """<html><body>
      <a class="news" href="/one">第一条</a>
      <div class="news"><a href="https://other.example/two">第二条</a></div>
    </body></html>"""
    rows = _parse_content(html, "selector", ".news", "https://example.com/base")
    assert [row["title"] for row in rows] == ["第一条", "第二条"]
    assert [row["url"] for row in rows] == [
        "https://example.com/one",
        "https://other.example/two",
    ]

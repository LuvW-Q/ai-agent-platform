"""Headless Chrome E2E for all registered HTML pages and core UI interactions."""

from __future__ import annotations

import argparse
import json
import time
from urllib.parse import urlsplit

import httpx

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


ROUTES = [
    "/dashboard",
    "/screen",
    "/agents",
    "/permissions",
    "/audit",
    "/messages",
    "/im",
    "/settings",
    "/query",
    "/models",
    "/skills",
    "/agent-management",
    "/de",
    "/rag",
    "/workflows",
    "/data-collection",
    "/smart-audit",
    "/admin-login",
    "/chat-management",
    "/creative",
    "/api-registry",
]


def login(base_url: str, username: str, password: str) -> dict:
    response = httpx.post(
        base_url + "/api/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    if response.is_error:
        raise RuntimeError(response.text)
    return response.json()


def wait_for_page(driver: webdriver.Chrome) -> None:
    WebDriverWait(driver, 15).until(
        lambda browser: browser.execute_script("return document.readyState") == "complete"
    )
    time.sleep(0.7)


def browser_errors(driver: webdriver.Chrome) -> list[str]:
    return [
        entry["message"]
        for entry in driver.get_log("browser")
        if entry["level"] == "SEVERE"
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("--base-url 仅允许本机 http/https 地址")
    tokens = login(args.base_url, args.username, args.password)

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1000")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})

    failures: list[str] = []
    results: list[dict] = []
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(args.base_url + "/login")
        wait_for_page(driver)
        login_text = driver.find_element(By.TAG_NAME, "body").text
        if "人脸识别登录" not in login_text or "本机演示" in login_text:
            failures.append("/login: 人脸登录文案未连接后端流程")
        driver.execute_script(
            "localStorage.setItem('access_token', arguments[0]);"
            "localStorage.setItem('refresh_token', arguments[1]);",
            tokens["access_token"],
            tokens["refresh_token"],
        )

        for route in ROUTES:
            driver.get(args.base_url + route)
            wait_for_page(driver)
            current_path = driver.execute_script("return location.pathname")
            text = driver.find_element(By.TAG_NAME, "body").text.strip()
            overflow = driver.execute_script(
                "return Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, 0)"
            )
            errors = browser_errors(driver)
            if current_path == "/login":
                failures.append(f"{route}: 被意外重定向到登录页")
            if not text:
                failures.append(f"{route}: 页面正文为空")
            if overflow > 2:
                failures.append(f"{route}: 页面横向溢出 {overflow}px")
            if errors:
                failures.extend(f"{route}: console {message}" for message in errors)
            results.append({"route": route, "path": current_path, "overflow": overflow, "console_errors": len(errors)})

        driver.get(args.base_url + "/im/chat?peer=1")
        wait_for_page(driver)
        if driver.execute_script("return location.pathname + location.search") != "/im?peer=1":
            failures.append("/im/chat?peer=1: 未按约定跳转到 /im?peer=1")

        driver.get(args.base_url + "/screen")
        WebDriverWait(driver, 15).until(lambda browser: len(browser.find_elements(By.TAG_NAME, "canvas")) > 0)
        errors = browser_errors(driver)
        if errors:
            failures.extend(f"/screen interaction: console {message}" for message in errors)

        driver.get(args.base_url + "/permissions")
        wait_for_page(driver)
        for tab, tbody in (("functions", "function-tbody"), ("bindings", "binding-tbody"), ("menus", "menu-tbody")):
            driver.find_element(By.CSS_SELECTOR, f"[data-tab='{tab}']").click()
            WebDriverWait(driver, 10).until(
                lambda browser: "加载中" not in browser.find_element(By.ID, tbody).text
            )
            if not driver.find_element(By.ID, tbody).text.strip():
                failures.append(f"/permissions: {tab} 数据为空")

        driver.get(args.base_url + "/query")
        wait_for_page(driver)
        query_input = driver.find_element(By.ID, "nl-input")
        query_input.clear()
        query_input.send_keys("近 7 天采集多少条新闻")
        driver.find_element(By.ID, "btn-query").click()
        WebDriverWait(driver, 15).until(
            lambda browser: browser.find_element(By.ID, "result-tag").text not in ("", "查询中...")
        )
        result_text = driver.find_element(By.ID, "result-area").text
        if "Mock" in result_text or "示例数据" in result_text:
            failures.append("/query: 近 7 天新闻仍返回前端伪造数据")
        if not driver.find_element(By.ID, "result-table").is_displayed():
            failures.append("/query: 真实问数结果未显示表格")
        errors = browser_errors(driver)
        if errors:
            failures.extend(f"/query interaction: console {message}" for message in errors)

        print(json.dumps({"pages": results, "failures": failures}, ensure_ascii=False, indent=2))
        if failures:
            raise SystemExit(1)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()

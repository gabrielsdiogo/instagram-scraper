#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import json
import os
from urllib.parse import unquote
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# =======================
# CONFIGURAÇÕES GERAIS
# =======================
SEEN_FILE = "seen_profiles.json"

tags_metadata = [
    {
        "name": "Scraping",
        "description": "Endpoints para coletar perfis salvos no Instagram. "
                       "É necessário enviar os cookies de autenticação válidos do Instagram.",
    }
]

app = FastAPI(
    title="Instagram Saved Scraper API",
    description="""
API para coletar perfis a partir dos **posts salvos no Instagram**.

### Como funciona:
1. Faça login manualmente no Instagram (navegador).
2. Copie os cookies `sessionid`, `ds_user_id` e `csrftoken`.
3. Envie via POST para `/scrape` com `max_profiles`.

### Endpoints:
- `POST /scrape` → Coleta os perfis e retorna dados em JSON.
    """,
    version="1.0.0",
    openapi_tags=tags_metadata,
)

# =======================
# MODELO DE REQUEST
# =======================
class Cookies(BaseModel):
    sessionid: str
    ds_user_id: str
    csrftoken: str


class ScrapeRequest(BaseModel):
    cookies: Cookies
    max_profiles: int = 10

    class Config:
        schema_extra = {
            "example": {
                "cookies": {
                    "sessionid": "2316205801%3ABa2OGkf2OZF1dD%3A15%3AAYhsE_uv2nMWt0Ij1067vCfkoLM3xqXKfJAui7r_ZVmd",
                    "ds_user_id": "2316205801",
                    "csrftoken": "cucwSj26QU2OZz1EnwxJm9GLBDDmFqK6"
                },
                "max_profiles": 10
            }
        }

# =======================
# FUNÇÕES AUXILIARES
# =======================
def load_seen_profiles() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen_profiles(seen: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False, indent=4)

def setup_driver(cookies: Cookies):
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    driver.get("https://www.instagram.com/")
    time.sleep(3)

    for k, v in cookies.dict().items():
        driver.add_cookie({"name": k, "value": v, "domain": ".instagram.com"})

    driver.refresh()
    time.sleep(5)
    return driver

def get_username(driver):
    elem = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.XPATH,
            '//*/div/div/div[2]/div/div/div[1]/div[1]/div[1]/section/main/div[1]/div[2]/div/div[1]/div/div/div/div/div/div[2]/div/div/div/a'
        ))
    )
    href = elem.get_attribute("href")
    return href.strip("/").split("/")[-1]

def scrape_saved_posts(driver, username, max_scrolls=50):
    SCROLL_PAUSE = 3
    saved_url = f"https://www.instagram.com/{username}/saved/all-posts/"
    driver.get(saved_url)
    time.sleep(5)

    last_height = driver.execute_script("return document.body.scrollHeight")
    scrolls = 0

    while scrolls < max_scrolls:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_PAUSE)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        scrolls += 1

    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")

    posts = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/p/") or href.startswith("/reel/") or href.startswith("/tv/"):
            posts.append("https://www.instagram.com" + href)

    return posts

def get_post_author(driver, post_url):
    driver.get(post_url)
    try:
        # tenta primeiro pelo og:url
        elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//meta[@property='og:url']"))
        )
        full_url = elem.get_attribute("content")
        parts = full_url.split("/")

        # se o og:url é de post (/p/, /reel/, /tv/), precisamos buscar o autor manualmente
        if len(parts) >= 4 and parts[3] in ["p", "reel", "tv"]:
            try:
                author_elem = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//header//a[contains(@href, '/')][1]"))
                )
                profile_url = author_elem.get_attribute("href")
                username = profile_url.strip("/").split("/")[-1]
            except:
                return None
        else:
            # caso normal, og:url já aponta para perfil
            username = parts[3]
            profile_url = f"https://www.instagram.com/{username}/"

        return {"username": username, "profile_url": profile_url}

    except Exception as e:
        print(f"[!] Erro ao capturar autor em {post_url}: {e}")
        return None

def get_profile_data(driver, username):
    url = f"https://www.instagram.com/{username}/"
    driver.get(url)
    time.sleep(2)

    profile_data = {
        "username": username,
        "full_name": "",
        "biography": "",
        "external_url": "",
        "address": "",
        "business_category": "",
    }

    try:
        elem = driver.find_element(By.XPATH,
            '//*/div/div/div[2]/div/div/div[1]/div[2]/div[1]/section/main/div/div/header/section[4]/div/div[1]/span'
        )
        profile_data["full_name"] = elem.text.strip()
    except:
        pass

    try:
        elem = driver.find_element(By.XPATH,
            '//*/div/div/div[2]/div/div/div[1]/div[2]/div[1]/section/main/div/div/header/section[4]/div/span/div/span'
        )
        profile_data["biography"] = elem.text.strip()
    except:
        pass

    try:
        elem = driver.find_element(By.XPATH,
            '//*/div/div/div[2]/div/div/div[1]/div[2]/div[1]/section/main/div/div/header/section[4]/div/h1'
        )
        profile_data["address"] = elem.text.strip()
    except:
        pass

    try:
        elem = driver.find_element(By.XPATH,
            '//*/div/div/div[2]/div/div/div[1]/div[2]/div[1]/section/main/div/div/header/section[4]/div/div[3]/div'
        )
        profile_data["business_category"] = elem.text.strip()
    except:
        pass

    try:
        elem = driver.find_element(By.XPATH,
            '//*/div/div/div[2]/div/div/div[1]/div[2]/div[1]/section/main/div/div/header/section[4]//a'
        )
        raw_url = elem.get_attribute("href")
        if raw_url:
            if "https://l.instagram.com/?u=" in raw_url:
                raw_url = raw_url.split("https://l.instagram.com/?u=")[-1].split("&")[0]
                raw_url = unquote(raw_url)
            profile_data["external_url"] = raw_url
    except:
        pass

    return profile_data

# =======================
# ENDPOINT
# =======================
@app.post("/scrape", tags=["Scraping"])
def scrape_instagram(request: ScrapeRequest):
    """
    ### Coleta perfis a partir dos posts salvos

    - **cookies**: objeto com `sessionid`, `ds_user_id` e `csrftoken`
    - **max_profiles**: número máximo de perfis inéditos a coletar nesta chamada

    Retorna JSON com lista de perfis:
    ```json
    {
      "profiles": [
        {
          "username": "empresa",
          "profile_url": "https://www.instagram.com/empresa/",
          "full_name": "Empresa LTDA",
          "biography": "Descrição do perfil",
          "external_url": "https://empresa.com.br",
          "address": "São Paulo, Brasil",
          "business_category": "Serviços"
        }
      ]
    }
    ```
    """
    cookies = request.cookies
    max_profiles = request.max_profiles

    seen = load_seen_profiles()

    driver = setup_driver(cookies)
    username = get_username(driver)
    posts = scrape_saved_posts(driver, username)

    profiles = []
    for post in posts:
        if len(profiles) >= max_profiles:
            break

        author_info = get_post_author(driver, post)
        if author_info and author_info["username"] not in seen:
            data = get_profile_data(driver, author_info["username"])
            data["profile_url"] = author_info["profile_url"]
            profiles.append(data)
            seen.add(author_info["username"])
        time.sleep(1)

    driver.quit()

    save_seen_profiles(seen)
    return {"profiles": profiles}

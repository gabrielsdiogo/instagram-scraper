#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import json
import os
from urllib.parse import unquote
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from selenium.webdriver import ActionChains
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
DATA_DIR = "data"
SEEN_FILE = os.path.join(DATA_DIR, "seen_profiles.json")

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


def load_seen_profiles():
    # cria a pasta se não existir
    os.makedirs(DATA_DIR, exist_ok=True)

    # cria o arquivo se não existir
    if not os.path.isfile(SEEN_FILE):
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_seen_profiles(profiles):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=4)

def setup_driver(cookies):
    chrome_options = Options()

    # Headless (pode remover se quiser ver o navegador abrindo)
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")

    # User-Agent realista
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    # Evitar bloqueios comuns
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # Profile persistente para cookies/cache
    chrome_options.add_argument("--user-data-dir=/tmp/chrome-profile")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    driver.get("https://www.instagram.com/")
    time.sleep(3)

    # Inserir cookies
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




# def scrape_saved_posts(driver, username, max_profiles=10, max_scrolls=30):
#     """
#     Abre os posts salvos, coleta perfis diretamente do modal do post.
#     Retorna até max_profiles perfis únicos.
#     """
#     SCROLL_PAUSE = 2
#     saved_url = f"https://www.instagram.com/{username}/saved/all-posts/"
#     driver.get(saved_url)
#     time.sleep(5)

#     profiles = []
#     seen = set()
#     scrolls = 0

#     while len(profiles) < max_profiles and scrolls < max_scrolls:
#         post_elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/'], a[href*='/reel/']")

#         for i in range(len(post_elements)):
#             if len(profiles) >= max_profiles:
#                 break

#             try:
#                 post_elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/'], a[href*='/reel/']")
#                 post = post_elements[i]

#                 driver.execute_script("arguments[0].scrollIntoView(true);", post)
#                 time.sleep(1)
#                 post.click()
#                 time.sleep(3)

#                 author_elem = WebDriverWait(driver, 6).until(
#                     EC.presence_of_element_located((By.CSS_SELECTOR, "article header a"))
#                 )
#                 profile_url = author_elem.get_attribute("href")
#                 username_author = profile_url.strip("/").split("/")[-1]

#                 if username_author not in seen:
#                     profiles.append({"username": username_author, "profile_url": profile_url})
#                     seen.add(username_author)
#                     print(f"[+] Extraído perfil: {username_author}")

#                 # fechar modal
#                 try:
#                     close_btn = WebDriverWait(driver, 5).until(
#                         EC.element_to_be_clickable((By.XPATH, "/html/body/div[last()]/div[1]/div/div[2]/div"))
#                     )
#                     close_btn.click()
#                     time.sleep(2)
#                 except:
#                     from selenium.webdriver.common.keys import Keys
#                     webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
#                     time.sleep(2)

#             except Exception as e:
#                 print(f"[!] Erro ao abrir post {i}: {e}")
#                 continue

#         driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
#         time.sleep(SCROLL_PAUSE)
#         scrolls += 1

#     return profiles

def scrape_saved_posts(driver, username, max_profiles=10, max_scrolls=50):
    """
    Percorre os posts salvos, clicando em cada um e extraindo username/profile_url.
    Só retorna perfis que ainda não estavam no arquivo de 'seen_profiles.json'.
    Continua rolando até atingir max_profiles ou acabar os posts.
    """
    SCROLL_PAUSE = 2
    saved_url = f"https://www.instagram.com/{username}/saved/all-posts/"
    driver.get(saved_url)
    time.sleep(5)

    seen_global = set(load_seen_profiles())  # já salvos no arquivo
    collected = []  # novos perfis nesta chamada
    seen_local = set()  # evita duplicar no mesmo request
    scrolls = 0

    while len(collected) < max_profiles and scrolls < max_scrolls:
        post_elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/'], a[href*='/reel/']")

        for i in range(len(post_elements)):
            if len(collected) >= max_profiles:
                break

            try:
                post = post_elements[i]
                driver.execute_script("arguments[0].scrollIntoView(true);", post)
                time.sleep(1)
                post.click()
                time.sleep(2.5)

                # pega perfil do autor no modal
                author_elem = WebDriverWait(driver, 6).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "article header a"))
                )
                profile_url = author_elem.get_attribute("href")
                username_author = profile_url.strip("/").split("/")[-1]

                # 🔹 só adiciona se não estiver nem no arquivo nem nos coletados desta request
                if username_author not in seen_global and username_author not in seen_local:
                    collected.append({"username": username_author, "profile_url": profile_url})
                    seen_local.add(username_author)
                    print(f"[+] Novo perfil encontrado: {username_author}")

                # fechar modal
                try:
                    close_btn = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, "/html/body/div[last()]/div[1]/div/div[2]/div"))
                    )
                    close_btn.click()
                    time.sleep(1.5)
                except:
                    from selenium.webdriver.common.keys import Keys
                    webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(1.5)

            except Exception as e:
                print(f"[!] Erro no post {i}: {e}")
                continue

        # rolar mais se ainda não atingimos o limite
        if len(collected) < max_profiles:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(SCROLL_PAUSE)
            scrolls += 1

    return collected




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
    cookies = request.cookies
    max_profiles = request.max_profiles

    try:
        driver = setup_driver(cookies)
        username = get_username(driver)

        # coleta apenas perfis inéditos
        new_profiles = scrape_saved_posts(driver, username, max_profiles=max_profiles)

        profiles = []
        for profile in new_profiles:
            data = get_profile_data(driver, profile["username"])
            data["profile_url"] = profile["profile_url"]
            profiles.append(data)

        driver.quit()

        # 🔹 salvar os novos perfis no arquivo global
        seen = set(load_seen_profiles())
        seen.update([p["username"] for p in new_profiles])
        save_seen_profiles(list(seen))

        return {"profiles": profiles}

    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"[❌ ERRO API /scrape] {e}\n{error_msg}")
        return {"error": str(e), "trace": error_msg}
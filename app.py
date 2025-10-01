#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import json
import os
from urllib.parse import unquote
from fastapi import FastAPI, HTTPException
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
import tempfile
import shutil

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
    """Carrega o arquivo JSON garantindo que sempre retorna lista de dicionários."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.isfile(SEEN_FILE):
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Normaliza caso existam listas antigas no formato [username, post_url]
    normalized = []
    for p in data:
        if isinstance(p, list) and len(p) == 2:
            normalized.append({"username": p[0], "post_url": p[1]})
        elif isinstance(p, dict):
            normalized.append(p)

    return normalized


def save_seen_profiles(profiles):
    """Salva no JSON garantindo que todos os itens sejam dicionários."""
    os.makedirs(DATA_DIR, exist_ok=True)

    normalized = []
    for p in profiles:
        if isinstance(p, list) and len(p) == 2:
            normalized.append({"username": p[0], "post_url": p[1]})
        elif isinstance(p, dict):
            normalized.append(p)

    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=4)

def setup_driver(cookies: Cookies):
    chrome_options = Options()
    # chrome_options.add_argument("--headless=new")
    # chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # 🔹 diretório temporário exclusivo para user-data
    user_data_dir = tempfile.mkdtemp()
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # anexa o path do user-data-dir dentro do driver
    driver.user_data_dir = user_data_dir  

    driver.get("https://www.instagram.com/")
    time.sleep(3)

    for k, v in cookies.dict().items():
        driver.add_cookie({"name": k, "value": v, "domain": ".instagram.com"})

    driver.refresh()
    time.sleep(5)
    return driver


def close_driver(driver):
    """Fecha o driver e remove o diretório temporário criado"""
    try:
        driver.quit()
    finally:
        if hasattr(driver, "user_data_dir") and os.path.exists(driver.user_data_dir):
            shutil.rmtree(driver.user_data_dir, ignore_errors=True)

def get_username(driver):
    elem = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.XPATH,
            '//*/div/div/div[2]/div/div/div[1]/div[1]/div[1]/section/main/div[1]/div[2]/div/div[1]/div/div/div/div/div/div[2]/div/div/div/a'
        ))
    )
    href = elem.get_attribute("href")
    return href.strip("/").split("/")[-1]




def close_post_modal(driver):
    """Fecha o modal do post com segurança"""
    try:
        # Primeiro tenta pelo botão padrão
        close_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "/html/body/div[5]/div[1]/div/div[2]/div"))
        )
        driver.execute_script("arguments[0].click();", close_button)
        time.sleep(2)
        return True
    except:
        try:
            # Se não conseguir, usa tecla ESC como fallback
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(2)
            return True
        except Exception as e:
            print(f"[!] Erro ao fechar modal: {e}")
            return False




def scrape_saved_posts(driver, username, max_profiles=10, scroll_limit=50):
    """
    1. Coleta usernames inéditos de posts salvos.
    2. Sempre salva o post_url aberto no arquivo, mesmo que username já exista.
    3. Só adiciona username na lista final se for novo.
    """
    SCROLL_PAUSE = 3
    saved_url = f"https://www.instagram.com/{username}/saved/all-posts/"
    driver.get(saved_url)
    time.sleep(5)

    seen_entries = load_seen_profiles()  # lista de dicts {username, post_url}
    seen_posts = {entry["post_url"] for entry in seen_entries if "post_url" in entry}
    seen_usernames = {entry["username"] for entry in seen_entries if "username" in entry}

    collected_profiles = []
    scrolls = 0
    last_height = driver.execute_script("return document.body.scrollHeight")

    while len(collected_profiles) < max_profiles and scrolls < scroll_limit:
        post_links = driver.find_elements(By.XPATH, '//a[contains(@href, "/p/")]')
        novos_encontrados = False

        for post in post_links:
            if len(collected_profiles) >= max_profiles:
                break
            try:
                post_url = post.get_attribute("href")

                # pula se já vimos este post
                if post_url in seen_posts:
                    continue

                # abre o modal
                driver.execute_script("arguments[0].click();", post)
                time.sleep(2)

                # pega username no modal
                author_elem = WebDriverWait(driver, 6).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "article header a"))
                )
                profile_url = author_elem.get_attribute("href")
                username_author = profile_url.strip("/").split("/")[-1]

                # sempre salva o post_url no arquivo
                seen_entries.append({"username": username_author, "post_url": post_url})
                seen_posts.add(post_url)

                # só coleta se for username inédito
                if username_author not in seen_usernames:
                    collected_profiles.append({
                        "username": username_author,
                        "post_url": post_url
                    })
                    seen_usernames.add(username_author)
                    novos_encontrados = True
                    print(f"[✓] Novo perfil coletado: {username_author} ({post_url})")

                close_post_modal(driver)

            except Exception as e:
                print(f"[!] Erro no post: {e}")
                close_post_modal(driver)

        # rolar se não atingiu limite
        if not novos_encontrados and len(collected_profiles) < max_profiles:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(SCROLL_PAUSE)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print("[!] Fim da página, sem mais posts.")
                break
            last_height = new_height
        scrolls += 1

    # salvar tudo (posts + usernames)
    save_seen_profiles(seen_entries)
    return collected_profiles






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

    driver = None
    try:
        driver = setup_driver(cookies)
        username = get_username(driver)

        # coleta apenas perfis inéditos abrindo apenas posts novos
        new_profiles = scrape_saved_posts(driver, username, max_profiles)

        profiles = []
        for profile in new_profiles:
            try:
                data = get_profile_data(driver, profile["username"])
                data["profile_url"] = f"https://www.instagram.com/{profile['username']}/"
                data["post_url"] = profile["post_url"]  # mantém o link do post
                profiles.append(data)
                print(f"[+] Dados extraídos de {profile['username']}")
            except Exception as e:
                print(f"[!] Erro ao extrair dados de {profile['username']}: {e}")

        close_driver(driver)
        return {"profiles": profiles}

    except Exception as e:
        if driver:
            try:
                driver.quit()
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Erro durante scraping: {str(e)}")

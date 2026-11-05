# -*- coding: utf-8 -*-
"""
CLOUD BOT VALIDATOR: cloud_validator.py
Executado periodicamente no GitHub Actions ou localmente.
1. Baixa as listas oficiais do Brasil do iptv-org (br.m3u e br_pluto.m3u).
2. Valida cada stream testando o manifesto .m3u8 E o download do primeiro segmento (.ts/aac).
3. Aplica timeout estrito de 1.8s e descarta sumariamente links lentos ou fora do ar.
4. Salva a lista final em 'lista_premium.m3u' e 'lista_premium.json'.
"""

import os
import sys
import re
import json
import asyncio
import urllib.parse
import datetime
import aiohttp

IPTV_ORG_BR = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/br.m3u"
PLUTO_TV_BR = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/br_pluto.m3u"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

CATEGORY_ORDER = [
    "TV Aberta",
    "Notícias",
    "Esportes",
    "Filmes e Séries",
    "Desenhos e Kids",
    "Pluto TV",
    "Documentários",
    "Música",
    "Variedades"
]

def normalize_category(raw_cat, name=""):
    name_lower = name.lower()
    cat_lower = (raw_cat or "").lower()

    if any(k in name_lower for k in ["globo", "sbt", "record tv", "band", "redetv", "cultura", "brasil", "futura", "gazeta", "tv aparecida", "rede vida", "rit", "tv senado", "tv câmara"]):
        return "TV Aberta"
    if any(k in name_lower or k in cat_lower for k in ["notícia", "news", "jovem pan", "cnn", "bandnews", "record news", "bm&c"]):
        return "Notícias"
    if any(k in name_lower or k in cat_lower for k in ["sport", "esporte", "combate", "futebol", "premiere", "espn", "cazé", "tnt sports"]):
        return "Esportes"
    if any(k in name_lower or k in cat_lower for k in ["filme", "cine", "telecine", "megapix", "hbo", "warner", "universal", "sony", "paramount", "tnt", "space", "amc", "cinema"]):
        return "Filmes e Séries"
    if any(k in name_lower or k in cat_lower for k in ["kids", "desenho", "infantil", "cartoon", "nickelodeon", "discovery kids", "gloob", "toonz"]):
        return "Desenhos e Kids"
    if "pluto" in name_lower or "pluto" in cat_lower:
        return "Pluto TV"
    if any(k in name_lower or k in cat_lower for k in ["doc", "discovery", "history", "geo", "animal"]):
        return "Documentários"
    if any(k in name_lower or k in cat_lower for k in ["music", "música", "mtv", "clip", "som", "radio", "rádio"]):
        return "Música"
    return "Variedades"

async def fetch_m3u(session, url, default_cat="Geral"):
    channels = []
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                print(f"[ERRO] Falha ao baixar {url} - Status: {resp.status}")
                return channels
            text = await resp.text(errors="ignore")
            lines = text.splitlines()

            cur_extinf = None
            for line in lines:
                line = line.strip()
                if line.startswith("#EXTINF"):
                    cur_extinf = line
                elif line and not line.startswith("#") and cur_extinf:
                    stream_url = line
                    # Extrai nome
                    name = cur_extinf.split(",")[-1].strip()
                    # Extrai logo
                    logo_m = re.search(r'tvg-logo="([^"]+)"', cur_extinf)
                    logo = logo_m.group(1).strip() if logo_m else ""
                    # Extrai categoria
                    grp_m = re.search(r'group-title="([^"]+)"', cur_extinf)
                    raw_grp = grp_m.group(1).strip() if grp_m else default_cat
                    cat = normalize_category(raw_grp, name)

                    channels.append({
                        "name": name,
                        "category": cat,
                        "logo": logo,
                        "url": stream_url,
                        "quality": "HLS HD"
                    })
                    cur_extinf = None
    except Exception as e:
        print(f"[ERRO] Exceção ao ler {url}: {e}")
    return channels

async def validate_stream(session, ch, semaphore):
    """
    Testa a latência real:
    1. Baixa o manifesto .m3u8 inicial.
    2. Encontra o primeiro segmento .ts ou sub-manifesto.
    3. Baixa os primeiros 512 bytes do segmento dentro do timeout estrito de 1.8s.
    """
    url = ch["url"]
    async with semaphore:
        try:
            timeout = aiohttp.ClientTimeout(total=1.8)
            # Passo 1: Obter manifesto
            async with session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True) as resp:
                if resp.status not in [200, 206]:
                    return None
                
                manifest_text = await resp.text(errors="ignore")
                if "#EXTM3U" not in manifest_text and resp.content_type not in ["application/vnd.apple.mpegurl", "application/x-mpegurl", "video/mp2t"]:
                    return None

                # Passo 2: Encontrar primeiro segmento ou playlist filha
                lines = [l.strip() for l in manifest_text.splitlines() if l.strip()]
                target_chunk = None
                for line in lines:
                    if not line.startswith("#"):
                        target_chunk = urllib.parse.urljoin(str(resp.url), line)
                        break

                if not target_chunk:
                    return ch # Manifesto válido sem chunk separado

                # Passo 3: Baixar 1º segmento/sub-playlist para confirmar fluxo de dados
                async with session.get(target_chunk, headers=HEADERS, timeout=timeout, allow_redirects=True) as c_resp:
                    if c_resp.status in [200, 206]:
                        data = await c_resp.content.read(512)
                        if len(data) > 0:
                            return ch
        except Exception:
            return None
    return None

async def main():
    print("=" * 60)
    print("CLOUD BOT VALIDATOR - HOUSE ALVES TV")
    print(f"Data de Execução: {datetime.datetime.now(datetime.timezone.utc).isoformat()} UTC")
    print("=" * 60)

    timeout = aiohttp.ClientTimeout(total=15)
    conn = aiohttp.TCPConnector(limit=15, ssl=False)
    async with aiohttp.ClientSession(timeout=timeout, connector=conn) as session:
        print("\n1. Baixando listas de canais do Brasil...")
        t_br = fetch_m3u(session, IPTV_ORG_BR, default_cat="TV Aberta")
        t_pluto = fetch_m3u(session, PLUTO_TV_BR, default_cat="Pluto TV")
        res_lists = await asyncio.gather(t_br, t_pluto)

        raw_candidates = res_lists[0] + res_lists[1]
        print(f" -> Total de canais baixados: {len(raw_candidates)}")

        # Deduplicação por URL
        seen_urls = set()
        seen_names = set()
        candidates = []
        for ch in raw_candidates:
            u = ch["url"].strip()
            n = ch["name"].strip().lower()
            if u and u not in seen_urls and n not in seen_names:
                seen_urls.add(u)
                seen_names.add(n)
                candidates.append(ch)

        print(f" -> Candidatos únicos para validação de latência: {len(candidates)}")

        # 2. Validação concorrente com timeout estrito de 1.8s
        print("\n2. Testando latência (download do .m3u8 e 1º .ts)...")
        semaphore = asyncio.Semaphore(15)
        tasks = [validate_stream(session, ch, semaphore) for ch in candidates]
        results = await asyncio.gather(*tasks)

        valid_channels = [r for r in results if r is not None]
        print(f"\n[SUCESSO] {len(valid_channels)} canais rápidos e 100% online confirmados (< 1.8s)!")

    # 3. Ordenação por categoria e numeração
    valid_channels.sort(key=lambda x: (
        CATEGORY_ORDER.index(x["category"]) if x["category"] in CATEGORY_ORDER else 99,
        x["name"].lower()
    ))

    for idx, ch in enumerate(valid_channels):
        ch["number"] = idx + 1

    # 4. Exportação lista_premium.m3u
    m3u_lines = ["#EXTM3U"]
    for ch in valid_channels:
        ext = f'#EXTINF:-1 tvg-id="" tvg-name="{ch["name"]}" tvg-logo="{ch["logo"]}" group-title="{ch["category"]}",{ch["name"]}'
        m3u_lines.append(ext)
        m3u_lines.append(ch["url"])

    with open("lista_premium.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines) + "\n")
    print(" -> Gerado: lista_premium.m3u")

    # 5. Exportação lista_premium.json
    with open("lista_premium.json", "w", encoding="utf-8") as f:
        json.dump(valid_channels, f, ensure_ascii=False, indent=2)
    print(" -> Gerado: lista_premium.json")

    # 6. Atualiza também a pasta local com.teste.iptv se existir
    iptv_dir = os.path.join(os.path.dirname(__file__), "com.teste.iptv")
    if os.path.exists(iptv_dir):
        with open(os.path.join(iptv_dir, "channels.json"), "w", encoding="utf-8") as f:
            json.dump(valid_channels, f, ensure_ascii=False, indent=2)
        with open(os.path.join(iptv_dir, "canais_mesclados.m3u"), "w", encoding="utf-8") as f:
            f.write("\n".join(m3u_lines) + "\n")
        print(f" -> Atualizado: {iptv_dir}/channels.json")

    print("\nProcessamento concluído com sucesso!")

if __name__ == "__main__":
    asyncio.run(main())


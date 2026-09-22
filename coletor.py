from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

FUSO_BRASILIA = timezone(timedelta(hours=-3))
ARQUIVO_JSON = "noticias.json"

# Buscas com viés positivo, conquistas e pautas progressistas/eleitorais
BUSCAS = [
    '("Governo Federal" OR "Lula" OR "Ministério") (investimento OR "novo PAC" OR "Minha Casa Minha Vida" OR emprego OR reajuste OR saúde OR SUS OR bolsa)',
    '("eleições" OR "campanha" OR "esquerda" OR "progressistas" OR "PT" OR "PSOL" OR "trabalhadores") (apoio OR proposta OR frente OR vitória OR crescimento)',
    '("direitos trabalhistas" OR "MST" OR "movimentos sociais" OR "igualdade" OR "indígenas" OR "meio ambiente" OR "salário mínimo")'
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def formatar_data(data_rfc):
    agora = datetime.now(FUSO_BRASILIA)
    if not data_rfc:
        return agora.strftime("%Y-%m-%d"), "Recente", 0
    try:
        dt = parsedate_to_datetime(data_rfc).astimezone(FUSO_BRASILIA)
        data_dia = dt.strftime("%Y-%m-%d")
        diferenca = agora - dt
        horas = int(diferenca.total_seconds() // 3600)
        minutos = int((diferenca.total_seconds() % 3600) // 60)

        if horas < 1:
            texto = f"Há {max(1, minutos)} min"
        elif horas < 24:
            texto = f"Há {horas}h"
        else:
            texto = dt.strftime("%d/%m %H:%M")
        return data_dia, texto, horas
    except Exception:
        return agora.strftime("%Y-%m-%d"), "Recente", 0

def extrair_imagem(texto_html):
    if not texto_html:
        return None
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', texto_html, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def classificar_categoria(texto):
    t = texto.lower()
    if any(k in t for k in ["eleição", "eleições", "candidat", "voto", "campanha", "comício", "disputa"]):
        return "eleicoes", "🗳️ Eleições & Campanhas"
    if any(k in t for k in ["emprego", "salário", "economia", "investimento", "pac", "inflação", "renda"]):
        return "economia", "📈 Conquistas & Economia"
    if any(k in t for k in ["sus", "educação", "saúde", "minha casa", "bolsa família", "farmácia", "escola"]):
        return "social", "🏛️ Políticas Públicas"
    if any(k in t for k in ["trabalhador", "sindicato", "mst", "movimento", "direitos", "indígena", "igualdade"]):
        return "direitos", "✊ Direitos & Mobilização"
    if any(k in t for k in ["clima", "meio ambiente", "amazônia", "cerrado", "sustentável", "transição"]):
        return "ambiente", "🌿 Meio Ambiente"
    return "geral", "📢 Notícias do Povo"

def limpar_texto(texto):
    if not texto:
        return ""
    texto = re.sub(r'<[^>]+>', '', texto)
    return html.unescape(texto).strip()

def extrair_veiculo(titulo):
    partes = titulo.rsplit(" - ", 1)
    if len(partes) > 1:
        return partes[0].strip(), partes[1].strip()
    return titulo.strip(), "Redação"

# 1. Carregar histórico anterior
historico = []
titulos_existentes = []
links_existentes = set()

if os.path.exists(ARQUIVO_JSON):
    try:
        with open(ARQUIVO_JSON, "r", encoding="utf-8") as f:
            historico = json.load(f)
            links_existentes = {item.get("link") for item in historico if "link" in item}
            titulos_existentes = [item.get("titulo", "").lower()[:35] for item in historico]
    except Exception as e:
        print(f"Aviso ao ler histórico: {e}")

novas = []

for busca in BUSCAS:
    url_encoded = urllib.parse.quote(busca)
    feed_url = f"https://news.google.com/rss/search?q={url_encoded}&hl=pt-BR&gl=BR&ceid=BR:pt-419"

    req = urllib.request.Request(feed_url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            conteudo = resp.read()

        raiz = ET.fromstring(conteudo)
        itens = raiz.find("channel").findall("item")

        for item in itens:
            titulo_raw = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            pubdate = item.find("pubDate").text if item.find("pubDate") is not None else ""
            desc_raw = item.find("description").text if item.find("description") is not None else ""

            if not titulo_raw or link in links_existentes:
                continue

            titulo_limpo, veiculo = extrair_veiculo(titulo_raw)
            titulo_chave = titulo_limpo.lower()[:35]

            if any(titulo_chave in t or t in titulo_chave for t in titulos_existentes):
                continue

            imagem = extrair_imagem(desc_raw)
            resumo = limpar_texto(desc_raw)
            if len(resumo) > 180:
                resumo = resumo[:180] + "..."

            cat_id, cat_nome = classificar_categoria(f"{titulo_limpo} {resumo}")
            data_dia, tempo_str, horas_decorridas = formatar_data(pubdate)

            nova_noticia = {
                "id": len(historico) + len(novas) + 1,
                "titulo": titulo_limpo,
                "veiculo": veiculo,
                "link": link,
                "resumo": resumo,
                "imagem": imagem,
                "categoria": cat_id,
                "categoria_label": cat_nome,
                "data_dia": data_dia,
                "hora": tempo_str,
                "urgente": horas_decorridas <= 2
            }

            novas.append(nova_noticia)
            links_existentes.add(link)
            titulos_existentes.append(titulo_chave)

            if len(novas) >= 25:
                break
    except Exception as e:
        print(f"Erro ao buscar feed '{busca[:25]}...': {e}")

dados_finais = (novas + historico)[:120]

with open(ARQUIVO_JSON, "w", encoding="utf-8") as f:
    json.dump(dados_finais, f, ensure_ascii=False, indent=2)

print(f"Sucesso: {len(novas)} novas matérias capturadas. Total no acervo: {len(dados_finais)}.")

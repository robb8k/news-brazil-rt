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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# 1. Feeds Diretos de Mídia Independente e Agências Públicas
FEEDS_RSS_DIRETOS = [
    ("Brasil de Fato", "https://www.brasildefato.com.br/feed/geral"),
    ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml"),
    ("Outras Palavras", "https://outraspalavras.net/feed/"),
    ("Vermelho", "https://vermelho.org.br/feed/")
]

# 2. Consultas Estruturadas no Google News com Foco em Realizações e Eleições
BUSCAS_GOOGLE = [
    '("Governo Federal" OR "Lula" OR "Ministério") (investimento OR "novo PAC" OR "Minha Casa Minha Vida" OR emprego OR reajuste OR saúde OR SUS OR "Bolsa Família")',
    '("eleições" OR "campanha" OR "esquerda" OR "progressistas" OR "PT" OR "PSOL" OR "frente popular") (apoio OR proposta OR liderança OR avanço OR comício)',
    '("direitos trabalhistas" OR "MST" OR "movimentos sociais" OR "reforma agrária" OR "salário mínimo" OR "indígenas" OR "transição ecológica")'
]

# Palavras-chave para descarte estrito (evitar narrativas contrárias)
TERMOS_EXCLUSAO = [
    "escândalo", "corrupção", "crise política", "rombo", "rejeição bate recorde",
    "derrota do governo", "investigado", "fraude", "oposição critica", "piora aprovação"
]

IMAGENS_PADRAO = {
    "eleicoes": "https://images.unsplash.com/photo-1540910419892-4a36d2c3266c?w=700&q=80",
    "economia": "https://images.unsplash.com/photo-1526304640581-d334cdbbf45e?w=700&q=80",
    "social": "https://images.unsplash.com/photo-1577495508048-b635879837f1?w=700&q=80",
    "direitos": "https://images.unsplash.com/photo-1582213782179-e0d53f98f2ca?w=700&q=80",
    "ambiente": "https://images.unsplash.com/photo-1511497584788-87676104235f?w=700&q=80",
    "geral": "https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=700&q=80"
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

def extrair_imagem(item_elem, texto_html):
    # Procura por enclosure
    enc = item_elem.find("enclosure")
    if enc is not None and enc.attrib.get("type", "").startswith("image"):
        return enc.attrib.get("url")
    
    # Procura tag img no corpo html
    if texto_html:
        match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', texto_html, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def classificar_categoria(texto):
    t = texto.lower()
    if any(k in t for k in ["eleição", "eleições", "candidat", "voto", "campanha", "comício", "disputa", "pesquisa eleitoral"]):
        return "eleicoes", "🗳️ Eleições & Campanhas"
    if any(k in t for k in ["emprego", "salário", "economia", "investimento", "pac", "renda", "pib", "indústria"]):
        return "economia", "📈 Conquistas & Economia"
    if any(k in t for k in ["sus", "educação", "saúde", "minha casa", "bolsa família", "farmácia", "universidade", "prouni"]):
        return "social", "🏛️ Políticas Públicas"
    if any(k in t for k in ["trabalhador", "sindicato", "mst", "movimento", "direitos", "indígena", "quilombola", "mulheres"]):
        return "direitos", "✊ Direitos & Mobilização"
    if any(k in t for k in ["clima", "meio ambiente", "amazônia", "cerrado", "sustentável", "transição", "energia limpa"]):
        return "ambiente", "🌿 Meio Ambiente"
    return "geral", "📢 Notícias do Povo"

def classificar_regiao(texto):
    t = texto.lower()
    if any(r in t for r in ["nordeste", "bahia", "salvador", "pernambuco", "recife", "ceará", "maranhão", "paraíba", "piauí", "alagoas", "sergipe", "rio grande do norte"]):
        return "Nordeste"
    if any(r in t for r in ["sudeste", "minas gerais", "belo horizonte", "são paulo", "rio de janeiro", "espírito santo"]):
        return "Sudeste"
    if any(r in t for r in ["norte", "amazônia", "pará", "amazonas", "amapá", "acre", "rondônia", "roraima", "tocantins"]):
        return "Norte"
    if any(r in t for r in ["sul", "paraná", "curitiba", "santa catarina", "rio grande do sul", "porto alegre"]):
        return "Sul"
    if any(r in t for r in ["centro-oeste", "brasília", "goiás", "mato grosso"]):
        return "Centro-Oeste"
    return "Nacional"

def limpar_texto(texto):
    if not texto:
        return ""
    texto = re.sub(r'<[^>]+>', '', texto)
    return html.unescape(texto).strip()

def extrair_veiculo(titulo, veiculo_padrao="Redação"):
    partes = titulo.rsplit(" - ", 1)
    if len(partes) > 1:
        return partes[0].strip(), partes[1].strip()
    return titulo.strip(), veiculo_padrao

# Carregar histórico anterior
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
        print(f"Aviso histórico: {e}")

novas = []

# Função auxiliar de parsing
def processar_feed(url, veiculo_padrao=""):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raiz = ET.fromstring(resp.read())
        itens = raiz.find("channel").findall("item") if raiz.find("channel") is not None else []
        for item in itens:
            titulo_raw = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            pubdate = item.find("pubDate").text if item.find("pubDate") is not None else ""
            desc_raw = item.find("description").text if item.find("description") is not None else ""

            if not titulo_raw or link in links_existentes:
                continue

            titulo_limpo, veiculo = extrair_veiculo(titulo_raw, veiculo_padrao or "Agência")
            titulo_chave = titulo_limpo.lower()[:35]

            # Filtro semântico de exclusão
            texto_teste = f"{titulo_limpo} {desc_raw}".lower()
            if any(termo in texto_teste for termo in TERMOS_EXCLUSAO):
                continue

            if any(titulo_chave in t or t in titulo_chave for t in titulos_existentes):
                continue

            resumo = limpar_texto(desc_raw)
            if len(resumo) > 170:
                resumo = resumo[:170] + "..."

            cat_id, cat_nome = classificar_categoria(f"{titulo_limpo} {resumo}")
            regiao = classificar_regiao(f"{titulo_limpo} {resumo}")
            data_dia, tempo_str, horas_decorridas = formatar_data(pubdate)
            img = extrair_imagem(item, desc_raw) or IMAGENS_PADRAO.get(cat_id, IMAGENS_PADRAO["geral"])

            # Estimativa de leitura (palavras / 130)
            palavras = len(f"{titulo_limpo} {resumo}".split())
            tempo_leitura = max(1, round(palavras / 25))

            novas.append({
                "id": len(historico) + len(novas) + 1,
                "titulo": titulo_limpo,
                "veiculo": veiculo,
                "link": link,
                "resumo": resumo,
                "imagem": img,
                "categoria": cat_id,
                "categoria_label": cat_nome,
                "regiao": regiao,
                "data_dia": data_dia,
                "hora": tempo_str,
                "tempo_leitura": f"{tempo_leitura} min de leitura",
                "urgente": horas_decorridas <= 2
            })

            links_existentes.add(link)
            titulos_existentes.append(titulo_chave)
            if len(novas) >= 35:
                break
    except Exception as e:
        print(f"Erro ao ler feed {url[:40]}: {e}")

# Processar feeds independentes diretos
for nome, feed in FEEDS_RSS_DIRETOS:
    processar_feed(feed, nome)

# Processar termos progressistas do Google News
for busca in BUSCAS_GOOGLE:
    url_encoded = urllib.parse.quote(busca)
    feed_url = f"https://news.google.com/rss/search?q={url_encoded}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    processar_feed(feed_url, "")

dados_finais = (novas + historico)[:120]

with open(ARQUIVO_JSON, "w", encoding="utf-8") as f:
    json.dump(dados_finais, f, ensure_ascii=False, indent=2)

print(f"Sucesso: {len(novas)} novas matérias capturadas com filtro editorial.")

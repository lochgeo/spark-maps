"""Build the administrative profiles for all 14 districts of Kerala.

Run from the project root:

    uv run --extra data python -m scripts.build_district_details

Sources used for each district:
  1. Official NIC district portals (*.nic.in / wayanad.gov.in) for taluk-wise
     revenue villages.
  2. Local Self Government Department (LSGD) directory (lsgkerala.gov.in) for
     the district panchayat, block panchayats -> gram panchayats,
     municipalities, and municipal corporations.
  3. Census 2011 via citypopulation.de (and Wikipedia's Municipalities of Kerala
     for post-2011 municipalities) for town populations and 2011 district
     demographics.
  4. Wikipedia district articles for revenue division groupings, taluk
     headquarters, and Lok Sabha constituencies.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import httpx
from lxml import html
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESULTS_CSV = DATA_DIR / "results.csv"
DISTRICT_DETAILS_JSON = DATA_DIR / "district_details.json"

RETRIEVED_DATE = "2026-10-31"
USER_AGENT = "spark-maps/0.3 (Kerala mapping project; data build script)"

# Display spelling harmonisation across LSGD, Census 2011, and district portals.
DISPLAY_NAMES = {
    "Cochin": "Kochi",
    "Guruvayoor": "Guruvayur",
    "Koothuparamba": "Kuthuparamba",
    "Kottarakara": "Kottarakkara",
    "Mattannur": "Mattanur",
    "Mavelikara": "Mavelikkara",
    "Nileshwar": "Nileshwaram",
    "Ottappalam": "Ottapalam",
    "Palai": "Pala",
    "Paravoor": "Paravur",
    "Quilandy": "Koyilandy",
    "Shoranur": "Shornur",
    "Sultan Bathery": "Sulthan Bathery",
    "Thalipparamba": "Taliparamba",
    "Thrippunithura": "Tripunithura",
    "VallatholNagar": "Vallathol Nagar",
    "Vatakara": "Vadakara",
    "Wadakanchery": "Wadakkanchery",
    "Wadakkancherry": "Wadakkanchery",
}

# 2011 populations for towns elevated to municipalities in 2010/2015 that were
# not listed as separate urban rows in the 2011 Census town table.
MUNICIPALITY_POP_2011 = {
    ("Pathanamthitta", "Pandalam"): 42793,
    ("Idukki", "Kattappana"): 42646,
    ("Ernakulam", "Koothattukulam"): 17523,
    ("Ernakulam", "Piravom"): 27229,
    ("Ernakulam", "Thrikkakara"): 65984,
    ("Palakkad", "Cherpulassery"): 41267,
    ("Malappuram", "Parappanangadi"): 71239,
    ("Malappuram", "Tanur"): 69534,
    ("Malappuram", "Valanchery"): 40318,
    ("Kozhikode", "Koduvally"): 48687,
    ("Kozhikode", "Mukkam"): 40670,
    ("Kozhikode", "Payyoli"): 49470,
    ("Wayanad", "Mananthavady"): 47974,
    ("Wayanad", "Sulthan Bathery"): 45417,
    ("Kannur", "Anthoor"): 28218,
    ("Kannur", "Iritty"): 40369,
    ("Kannur", "Sreekandapuram"): 33489,
    ("Kasaragod", "Nileshwaram"): 39752,
}

# District metadata: LSGD code, CityPopulation slugs, Wikipedia revision,
# summary, revenue divisions, taluk HQs, and Parliamentary constituencies.
DISTRICT_SPECS = {
    "Kasaragod": {
        "lsgd_code": 14,
        "cp_town_slug": "3201__kasaragod",
        "cp_admin_slug": "588__kasaragod",
        "portal_url": "https://kasargod.nic.in/en/tehsil/",
        "wiki_title": "Kasaragod_district",
        "wiki_oldid": 1381013932,
        "summary": (
            "Northernmost district of Kerala, bordering Karnataka and the Arabian Sea. "
            "Known for its linguistic diversity (Sapthabhasha Sangamabhoomi), historic "
            "Bekal Fort, and coir and handloom industries."
        ),
        "revenue_divisions": [
            {"name": "Kasaragod", "taluks": ["Manjeshwaram", "Kasaragod"]},
            {"name": "Kanhangad", "taluks": ["Hosdurg", "Vellarikundu"]},
        ],
        "taluk_hqs": {
            "Kasaragod": "Kasaragod",
            "Hosdurg": "Kanhangad",
            "Manjeshwaram": "Uppala",
            "Vellarikundu": "Vellarikundu",
        },
        "parliamentary_seats": ["Kasaragod"],
    },
    "Kannur": {
        "lsgd_code": 13,
        "cp_town_slug": "3202__kannur",
        "cp_admin_slug": "589__kannur",
        "portal_url": "https://kannur.nic.in/en/village-panchayats/",
        "wiki_title": "Kannur_district",
        "wiki_oldid": 1381926834,
        "summary": (
            "North Malabar coastal district renowned for Theyyam ritual art, handloom "
            "exports, and historic port towns. Home to Kerala's only cantonment board "
            "and fourth international airport at Mattanur."
        ),
        "revenue_divisions": [
            {"name": "Taliparamba", "taluks": ["Payyanur", "Taliparamba", "Kannur"]},
            {"name": "Thalassery", "taluks": ["Thalassery", "Iritty"]},
        ],
        "taluk_hqs": {
            "Payyanur": "Payyanur",
            "Taliparamba": "Taliparamba",
            "Kannur": "Kannur",
            "Thalassery": "Thalassery",
            "Iritty": "Iritty",
        },
        "parliamentary_seats": ["Kasaragod", "Kannur", "Vadakara"],
    },
    "Wayanad": {
        "lsgd_code": 12,
        "cp_town_slug": "3203__wayanad",
        "cp_admin_slug": "590__wayanad",
        "portal_url": "https://wayanad.gov.in/en/village-panchayats/",
        "wiki_title": "Wayanad_district",
        "wiki_oldid": 1382416204,
        "summary": (
            "High-altitude plateau district in the Western Ghats, bordering Karnataka "
            "and Tamil Nadu. It is Kerala's least populous district, known for coffee, "
            "tea and spice plantations, wildlife sanctuaries, and indigenous heritage."
        ),
        "revenue_divisions": [
            {"name": "Mananthavady", "taluks": ["Mananthavady", "Sulthan Bathery", "Vythiri"]},
        ],
        "taluk_hqs": {
            "Mananthavady": "Mananthavady",
            "Sulthan Bathery": "Sulthan Bathery",
            "Vythiri": "Kalpetta",
        },
        "parliamentary_seats": ["Wayanad"],
    },
    "Kozhikode": {
        "lsgd_code": 11,
        "cp_town_slug": "3204__kozhikode",
        "cp_admin_slug": "591__kozhikode",
        "portal_url": "https://kozhikode.nic.in/en/about-district/adminstration/villages/",
        "wiki_title": "Kozhikode_district",
        "wiki_oldid": 1382633315,
        "summary": (
            "Historic Malabar port district on the Arabian Sea where Vasco da Gama "
            "landed in 1498. Centred on Kozhikode city, a UNESCO City of Literature "
            "and major commercial and educational hub of northern Kerala."
        ),
        "revenue_divisions": [
            {"name": "Vadakara", "taluks": ["Vadakara", "Koyilandy"]},
            {"name": "Kozhikode", "taluks": ["Thamarassery", "Kozhikode"]},
        ],
        "taluk_hqs": {
            "Vadakara": "Vadakara",
            "Koyilandy": "Koyilandy",
            "Thamarassery": "Thamarassery",
            "Kozhikode": "Kozhikode",
        },
        "parliamentary_seats": ["Vadakara", "Kozhikode", "Wayanad"],
    },
    "Malappuram": {
        "lsgd_code": 10,
        "cp_town_slug": "3205__malappuram",
        "cp_admin_slug": "592__malappuram",
        "portal_url": "https://malappuram.nic.in/en/village-panchayats/",
        "wiki_title": "Malappuram_district",
        "wiki_oldid": 1380830725,
        "summary": (
            "Kerala's most populous district, stretching from the Nilgiri hills to the "
            "Arabian Sea. It has the highest number of legislative assembly seats (16), "
            "blocks (15), gram panchayats (94), and municipalities (12) in the state."
        ),
        "revenue_divisions": [
            {"name": "Perinthalmanna", "taluks": ["Nilambur", "Eranad", "Perinthalmanna"]},
            {"name": "Tirur", "taluks": ["Kondotty", "Tirurangadi", "Tirur", "Ponnani"]},
        ],
        "taluk_hqs": {
            "Nilambur": "Nilambur",
            "Eranad": "Manjeri",
            "Perinthalmanna": "Perinthalmanna",
            "Kondotty": "Kondotty",
            "Tirurangadi": "Tirurangadi",
            "Tirur": "Tirur",
            "Ponnani": "Ponnani",
        },
        "parliamentary_seats": ["Wayanad", "Malappuram", "Ponnani"],
    },
    "Palakkad": {
        "lsgd_code": 9,
        "cp_town_slug": "3206__palakkad",
        "cp_admin_slug": "593__palakkad",
        "portal_url": "https://palakkad.nic.in/en/villages/",
        "wiki_title": "Palakkad_district",
        "wiki_oldid": 1376710189,
        "summary": (
            "Largest district in Kerala by area, straddling the Palakkad Gap in the "
            "Western Ghats. Known as the granary of Kerala for its extensive paddy "
            "fields, dams, Silent Valley National Park, and industrial corridor."
        ),
        "revenue_divisions": [
            {"name": "Palakkad", "taluks": ["Palakkad", "Chittur", "Alathur"]},
            {
                "name": "Ottapalam",
                "taluks": ["Ottapalam", "Pattambi", "Mannarkkad", "Attappadi"],
            },
        ],
        "taluk_hqs": {
            "Palakkad": "Palakkad",
            "Chittur": "Chittur",
            "Alathur": "Alathur",
            "Ottapalam": "Ottapalam",
            "Pattambi": "Pattambi",
            "Mannarkkad": "Mannarkkad",
            "Attappadi": "Agali",
        },
        "parliamentary_seats": ["Ponnani", "Palakkad", "Alathur"],
    },
    "Thrissur": {
        "lsgd_code": 8,
        "cp_town_slug": "3207__thrissur",
        "cp_admin_slug": "594__thrissur",
        "portal_url": "https://thrissur.nic.in/en/villages-255/",
        "wiki_title": "Thrissur_district",
        "wiki_oldid": 1380194348,
        "summary": (
            "Central Kerala district on the Arabian Sea, known as the state's cultural "
            "capital. It is the fourth-largest district by area and the most urbanised "
            "after Ernakulam."
        ),
        "revenue_divisions": [
            {
                "name": "Thrissur",
                "taluks": ["Thrissur", "Chavakkad", "Talappilly", "Kunnamkulam"],
            },
            {
                "name": "Irinjalakuda",
                "taluks": ["Mukundapuram", "Chalakudy", "Kodungallur"],
            },
        ],
        "taluk_hqs": {
            "Kodungallur": "Kodungallur",
            "Mukundapuram": "Irinjalakuda",
            "Talappilly": "Wadakkanchery",
            "Thrissur": "Thrissur",
            "Chavakkad": "Chavakkad",
            "Chalakudy": "Chalakudy",
            "Kunnamkulam": "Kunnamkulam",
        },
        "parliamentary_seats": ["Thrissur", "Chalakudy", "Alathur"],
    },
    "Ernakulam": {
        "lsgd_code": 7,
        "cp_town_slug": "3208__ernakulam",
        "cp_admin_slug": "595__ernakulam",
        "portal_url": "https://ernakulam.nic.in/en/village-panchayats/",
        "wiki_title": "Ernakulam_district",
        "wiki_oldid": 1380246159,
        "summary": (
            "Commercial, industrial, and IT heartland of Kerala, encompassing Greater "
            "Kochi and its port. It is the state's most urbanised district, with 13 "
            "municipalities, a municipal corporation, and the Kerala High Court."
        ),
        "revenue_divisions": [
            {
                "name": "Fort Kochi",
                "taluks": ["Kanayannur", "Kochi", "North Paravur", "Aluva"],
            },
            {
                "name": "Muvattupuzha",
                "taluks": ["Muvattupuzha", "Kothamangalam", "Kunnathunad"],
            },
        ],
        "taluk_hqs": {
            "Aluva": "Aluva",
            "Muvattupuzha": "Muvattupuzha",
            "North Paravur": "North Paravur",
            "Kothamangalam": "Kothamangalam",
            "Kanayannur": "Ernakulam",
            "Kunnathunad": "Perumbavoor",
            "Kochi": "Fort Kochi",
        },
        "parliamentary_seats": ["Chalakudy", "Ernakulam", "Idukki", "Kottayam"],
    },
    "Idukki": {
        "lsgd_code": 6,
        "cp_town_slug": "3209__idukki",
        "cp_admin_slug": "596__idukki",
        "portal_url": "https://idukki.nic.in/en/revenue/",
        "wiki_title": "Idukki_district",
        "wiki_oldid": 1379150728,
        "summary": (
            "Rugged high-range district in the Western Ghats and the second-largest "
            "district by area. Famous for Munnar's tea estates, cardamom hills, "
            "Periyar Tiger Reserve, and the Idukki arch dam, which generates much of "
            "Kerala's hydroelectric power."
        ),
        "revenue_divisions": [
            {"name": "Devikulam", "taluks": ["Devikulam", "Udumbanchola", "Peermade"]},
            {"name": "Idukki", "taluks": ["Idukki", "Thodupuzha"]},
        ],
        "taluk_hqs": {
            "Devikulam": "Devikulam",
            "Thodupuzha": "Thodupuzha",
            "Udumbanchola": "Nedumkandam",
            "Peermade": "Peermade",
            "Idukki": "Painavu",
        },
        "parliamentary_seats": ["Idukki"],
    },
    "Kottayam": {
        "lsgd_code": 5,
        "cp_town_slug": "3210__kottayam",
        "cp_admin_slug": "597__kottayam",
        "portal_url": "https://kottayam.nic.in/en/tehsil/",
        "wiki_title": "Kottayam_district",
        "wiki_oldid": 1376795030,
        "summary": (
            "Central Travancore district bordered by Vembanad Lake on the west and the "
            "Western Ghats on the east. Renowned as Akshara Nagari (city of letters) for "
            "its publishing history, rubber plantations, and Kerala's highest literacy rate."
        ),
        "revenue_divisions": [
            {"name": "Kottayam", "taluks": ["Changanassery", "Kanjirappally", "Kottayam"]},
            {"name": "Pala", "taluks": ["Meenachil", "Vaikom"]},
        ],
        "taluk_hqs": {
            "Changanassery": "Changanassery",
            "Kanjirappally": "Kanjirappally",
            "Kottayam": "Kottayam",
            "Meenachil": "Pala",
            "Vaikom": "Vaikom",
        },
        "parliamentary_seats": ["Kottayam", "Pathanamthitta", "Mavelikkara"],
    },
    "Alappuzha": {
        "lsgd_code": 4,
        "cp_town_slug": "3211__alappuzha",
        "cp_admin_slug": "598__alappuzha",
        "portal_url": "https://alappuzha.nic.in/en/villages/",
        "wiki_title": "Alappuzha_district",
        "wiki_oldid": 1381592621,
        "summary": (
            "Smallest district in Kerala by area, set along the Laccadive Sea and the "
            "Vembanad backwater network. Home to Kuttanad's below-sea-level rice "
            "farming, snake-boat races, and traditional coir manufacturing."
        ),
        "revenue_divisions": [
            {"name": "Alappuzha", "taluks": ["Cherthala", "Ambalappuzha", "Kuttanad"]},
            {"name": "Chengannur", "taluks": ["Karthikappally", "Chengannur", "Mavelikkara"]},
        ],
        "taluk_hqs": {
            "Cherthala": "Cherthala",
            "Ambalappuzha": "Alappuzha",
            "Kuttanad": "Mankombu",
            "Karthikappally": "Haripad",
            "Chengannur": "Chengannur",
            "Mavelikkara": "Mavelikkara",
        },
        "parliamentary_seats": ["Alappuzha", "Mavelikkara"],
    },
    "Pathanamthitta": {
        "lsgd_code": 3,
        "cp_town_slug": "3212__pathanamthitta",
        "cp_admin_slug": "599__pathanamthitta",
        "portal_url": "https://pathanamthitta.nic.in/en/revenue/",
        "wiki_title": "Pathanamthitta_district",
        "wiki_oldid": 1378133459,
        "summary": (
            "Forested inland district in southern Kerala, over half of which is covered "
            "by reserve forests along the Western Ghats. Known as headquarters of "
            "pilgrimage tourism in Kerala, hosting Sabarimala, Aranmula, and Maramon."
        ),
        "revenue_divisions": [
            {"name": "Adoor", "taluks": ["Adoor", "Konni", "Kozhencherry"]},
            {"name": "Thiruvalla", "taluks": ["Ranni", "Mallappally", "Thiruvalla"]},
        ],
        "taluk_hqs": {
            "Adoor": "Adoor",
            "Kozhencherry": "Pathanamthitta",
            "Ranni": "Ranni",
            "Mallappally": "Mallappally",
            "Thiruvalla": "Thiruvalla",
            "Konni": "Konni",
        },
        "parliamentary_seats": ["Pathanamthitta"],
    },
    "Kollam": {
        "lsgd_code": 2,
        "cp_town_slug": "3213__kollam",
        "cp_admin_slug": "600__kollam",
        "portal_url": "https://kollam.nic.in/en/tehsil/",
        "wiki_title": "Kollam_district",
        "wiki_oldid": 1382278095,
        "summary": (
            "Southern Kerala district stretching from the Arabian Sea and Ashtamudi "
            "Lake to the Aryankavu pass on the Tamil Nadu border. An ancient maritime "
            "trading port (Quilon) and the global centre of India's cashew industry."
        ),
        "revenue_divisions": [
            {"name": "Kollam", "taluks": ["Kollam", "Karunagappally", "Kunnathur"]},
            {"name": "Punalur", "taluks": ["Kottarakkara", "Pathanapuram", "Punalur"]},
        ],
        "taluk_hqs": {
            "Kollam": "Kollam",
            "Kottarakkara": "Kottarakkara",
            "Pathanapuram": "Pathanapuram",
            "Karunagappally": "Karunagappally",
            "Kunnathur": "Sasthamkotta",
            "Punalur": "Punalur",
        },
        "parliamentary_seats": ["Kollam", "Mavelikkara", "Alappuzha"],
    },
    "Thiruvananthapuram": {
        "lsgd_code": 1,
        "cp_town_slug": "3214__thiruvananthapuram",
        "cp_admin_slug": "601__thiruvananthapuram",
        "portal_url": "https://trivandrum.nic.in/en/villages/",
        "wiki_title": "Thiruvananthapuram_district",
        "wiki_oldid": 1380574560,
        "summary": (
            "Southernmost district of Kerala and home to the state capital. Hosts the "
            "Legislative Assembly, Vikram Sarabhai Space Centre, Technopark, Vizhinjam "
            "International Seaport, and the highest population density in the state."
        ),
        "revenue_divisions": [
            {
                "name": "Thiruvananthapuram",
                "taluks": ["Thiruvananthapuram", "Chirayinkeezhu", "Varkala", "Neyyattinkara"],
            },
            {"name": "Nedumangad", "taluks": ["Nedumangad", "Kattakada"]},
        ],
        "taluk_hqs": {
            "Thiruvananthapuram": "Thiruvananthapuram",
            "Neyyattinkara": "Neyyattinkara",
            "Nedumangad": "Nedumangad",
            "Kattakada": "Kattakada",
            "Chirayinkeezhu": "Attingal",
            "Varkala": "Varkala",
        },
        "parliamentary_seats": ["Attingal", "Thiruvananthapuram"],
    },
}


def display_name(name: str) -> str:
    cleaned = " ".join(name.split()).strip()
    return DISPLAY_NAMES.get(cleaned, cleaned)


def tidy_village(name: str) -> str:
    cleaned = re.sub(r"\s*[\u2013\u2014\ufffd]+\s*", " - ", " ".join(name.split()).strip())
    words = []
    for word in cleaned.split():
        if word.isupper() and len(word) > 2 and not re.fullmatch(r"[IVX]+", word):
            words.append(word.capitalize())
        elif word.islower():
            words.append(word[:1].upper() + word[1:])
        else:
            words.append(word)
    return " ".join(words)


_PORTAL_CLIENT = httpx.Client(
    transport=httpx.HTTPTransport(retries=3),
    follow_redirects=True,
    timeout=30,
    verify=False,
    headers={"User-Agent": USER_AGENT},
)


def fetch_url(url: str) -> bytes:
    response = _PORTAL_CLIENT.get(url)
    response.raise_for_status()
    return response.content


def fetch_html(url: str):
    return html.fromstring(fetch_url(url).decode("utf-8", errors="replace"))


# ---------- Taluk & village extractors per district portal ----------


def extract_kasaragod_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    mapping = [
        ("Kasaragod", "Kasargod Taluk"),
        ("Hosdurg", "Hosdurg Taluk"),
        ("Manjeshwaram", "Manjeshwaram Taluk"),
        ("Vellarikundu", "Vellarikundu Taluk"),
    ]
    taluks = []
    for taluk_name, caption in mapping:
        for table in doc.xpath("//table"):
            cap = " ".join(table.xpath("string(caption)").split())
            if caption.lower() in cap.lower():
                villages = [
                    tidy_village(" ".join(tr.xpath("string(./td[1])").split()))
                    for tr in table.xpath(".//tbody/tr")
                    if tr.xpath("./td[1]")
                ]
                taluks.append(
                    {
                        "name": taluk_name,
                        "headquarters": hqs[taluk_name],
                        "villages": [v for v in villages if v],
                    }
                )
                break
    return taluks


def extract_kannur_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    pdfs = [
        (
            "Kannur",
            "https://cdn.s3waas.gov.in/s3060ad92489947d410d897474079c1477/uploads/2018/03/2018042062.pdf",
        ),
        (
            "Taliparamba",
            "https://cdn.s3waas.gov.in/s3060ad92489947d410d897474079c1477/uploads/2018/03/2018042024.pdf",
        ),
        (
            "Thalassery",
            "https://cdn.s3waas.gov.in/s3060ad92489947d410d897474079c1477/uploads/2018/03/2018033177.pdf",
        ),
        (
            "Iritty",
            "https://cdn.s3waas.gov.in/s3060ad92489947d410d897474079c1477/uploads/2018/03/2018033121.pdf",
        ),
        (
            "Payyanur",
            "https://cdn.s3waas.gov.in/s3060ad92489947d410d897474079c1477/uploads/2018/03/2018042019.pdf",
        ),
    ]
    fixes = {
        "Kannur2": "Kannur 2",
        "Moraz ha": "Morazha",
        "New New": "New Mahe",
        "Thaliparambu": "Taliparamba",
    }
    taluks = []
    for taluk_name, pdf_url in pdfs:
        raw = fetch_url(pdf_url)
        reader = PdfReader(io.BytesIO(raw))
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        tokens = [tok.strip() for tok in full_text.split() if tok.strip()]
        villages = []
        for idx, tok in enumerate(tokens):
            if re.fullmatch(r"13\d{4}", tok):
                parts = []
                for j in range(idx + 1, min(idx + 8, len(tokens))):
                    if (
                        re.search(r"\d{5,}", tokens[j])
                        or "@" in tokens[j]
                        or "http" in tokens[j]
                    ):
                        break
                    parts.append(tokens[j])
                vname = " ".join(parts).strip()
                if vname:
                    vname = fixes.get(vname, vname)
                    villages.append(tidy_village(vname))
        taluks.append(
            {
                "name": taluk_name,
                "headquarters": hqs[taluk_name],
                "villages": villages,
            }
        )
    return taluks


def extract_wayanad_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    mapping = [
        ("Sulthan Bathery", "SULTHAN BATHERY TALUK"),
        ("Vythiri", "VYTHIRI TALUK"),
        ("Mananthavady", "MANANTHAVADY TALUK"),
    ]
    taluks = []
    for taluk_name, caption in mapping:
        for table in doc.xpath("//table"):
            cap = " ".join(table.xpath("string(caption)").split())
            if caption.lower() in cap.lower():
                villages = [
                    tidy_village(
                        re.sub(
                            r"\s+Village$",
                            "",
                            " ".join(tr.xpath("string(./td[1])").split()),
                            flags=re.I,
                        )
                    )
                    for tr in table.xpath(".//tbody/tr")
                    if tr.xpath("./td[1]")
                ]
                taluks.append(
                    {
                        "name": taluk_name,
                        "headquarters": hqs[taluk_name],
                        "villages": [v for v in villages if v],
                    }
                )
                break
    return taluks


def extract_kozhikode_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    mapping = [
        ("Kozhikode", "Kozhikode Taluk"),
        ("Koyilandy", "Koyilandy Taluk"),
        ("Vadakara", "Vadakara Taluk"),
        ("Thamarassery", "Thamarassery Taluk"),
    ]
    taluks = []
    for taluk_name, caption in mapping:
        for table in doc.xpath("//table"):
            cap = " ".join(table.xpath("string(caption)").split())
            if caption.lower() in cap.lower():
                villages = [
                    tidy_village(" ".join(tr.xpath("string(./td[2])").split()))
                    for tr in table.xpath(".//tbody/tr")
                    if tr.xpath("./td[2]")
                ]
                taluks.append(
                    {
                        "name": taluk_name,
                        "headquarters": hqs[taluk_name],
                        "villages": [v for v in villages if v],
                    }
                )
                break
    return taluks


def extract_malappuram_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    mapping = [
        ("Eranad", "Ernad Taluk"),
        ("Perinthalmanna", "Perinthalmanna taluk"),
        ("Ponnani", "Ponnani taluk"),
        ("Nilambur", "Nilambur taluk"),
        ("Tirurangadi", "Tirurangadi taluk"),
        ("Tirur", "Tirur taluk"),
        ("Kondotty", "Kondotty taluk"),
    ]
    taluks = []
    for taluk_name, caption in mapping:
        for table in doc.xpath("//table"):
            cap = " ".join(table.xpath("string(caption)").split())
            if caption.lower() == cap.lower():
                villages = [
                    tidy_village(" ".join(td.xpath("string(.)").split()))
                    for td in table.xpath(".//tbody/tr/td")
                ]
                taluks.append(
                    {
                        "name": taluk_name,
                        "headquarters": hqs[taluk_name],
                        "villages": [v for v in villages if v],
                    }
                )
                break
    return taluks


def extract_palakkad_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    order = [
        "Palakkad",
        "Chittur",
        "Alathur",
        "Ottapalam",
        "Mannarkkad",
        "Pattambi",
        "Attappadi",
    ]
    tables = doc.xpath("//table")
    taluks = []
    for taluk_name, table in zip(order, tables, strict=True):
        villages = [
            tidy_village(" ".join(tr.xpath("string(./td[2])").split()))
            for tr in table.xpath(".//tbody/tr")
            if len(tr.xpath("./td")) >= 2
        ]
        taluks.append(
            {
                "name": taluk_name,
                "headquarters": hqs[taluk_name],
                "villages": [v for v in villages if v],
            }
        )
    return taluks


def extract_ernakulam_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    mapping = [
        ("Aluva", "ALUVA"),
        ("Muvattupuzha", "MUVATTUPUZHA"),
        ("North Paravur", "PARAVUR"),
        ("Kothamangalam", "KOTHAMANGALAM"),
        ("Kanayannur", "KANAYANNUR"),
        ("Kunnathunad", "KUNNATHUNAD"),
        ("Kochi", "KOCHI"),
    ]
    taluks = []
    for taluk_name, caption in mapping:
        for table in doc.xpath("//table"):
            cap = " ".join(table.xpath("string(caption)").split())
            if cap.upper() == caption:
                td = table.xpath(".//tbody/tr[1]/td[1]")[0]
                villages = []
                for li in td.xpath(".//li[not(.//li)]"):
                    parts = [
                        tidy_village(re.sub(r"^\d+\s*", "", p.strip()))
                        for p in li.itertext()
                        if p.strip()
                    ]
                    villages.extend(p for p in parts if p)
                taluks.append(
                    {
                        "name": taluk_name,
                        "headquarters": hqs[taluk_name],
                        "villages": villages,
                    }
                )
                break
    return taluks


def extract_idukki_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    mapping = [
        ("Devikulam", "Devikulam Taluk"),
        ("Thodupuzha", "ThodupuzhaTaluk"),
        ("Udumbanchola", "Udumbanchola Taluk"),
        ("Peermade", "Peermade Taluk"),
        ("Idukki", "Idukki Taluk"),
    ]
    taluks = []
    for taluk_name, caption in mapping:
        for table in doc.xpath("//table"):
            cap = " ".join(table.xpath("string(caption)").split())
            if caption.lower() in cap.lower():
                villages = [
                    tidy_village(" ".join(tr.xpath("string(./td[2])").split()))
                    for tr in table.xpath(".//tbody/tr")
                    if tr.xpath("./td[2]")
                ]
                taluks.append(
                    {
                        "name": taluk_name,
                        "headquarters": hqs[taluk_name],
                        "villages": [v for v in villages if v],
                    }
                )
                break
    return taluks


def extract_kottayam_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    mapping = [
        ("Changanassery", "Changanacherry Taluk"),
        ("Kanjirappally", "Kanjirappally Taluk"),
        ("Kottayam", "Kottayam Taluk"),
        ("Meenachil", "Meenachil Taluk"),
        ("Vaikom", "Vaikom Taluk"),
    ]
    taluks = []
    for taluk_name, caption in mapping:
        for table in doc.xpath("//table"):
            cap = " ".join(table.xpath("string(caption)").split())
            if caption.lower() in cap.lower():
                villages = [
                    tidy_village(
                        re.sub(
                            r"^\d+\.\s*",
                            "",
                            " ".join(tr.xpath("string(./td[1])").split()),
                        )
                    )
                    for tr in table.xpath(".//tbody/tr")
                    if tr.xpath("./td[1]")
                ]
                taluks.append(
                    {
                        "name": taluk_name,
                        "headquarters": hqs[taluk_name],
                        "villages": [v for v in villages if v],
                    }
                )
                break
    return taluks


def extract_alappuzha_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    mapping = [
        ("Cherthala", "Cherthala"),
        ("Ambalappuzha", "Ambalappuzha"),
        ("Kuttanad", "Kuttanad"),
        ("Karthikappally", "Karthikapally"),
        ("Chengannur", "Taluk -Chengannur"),
        ("Mavelikkara", "Mavelikkara"),
    ]
    taluks = []
    for taluk_name, caption in mapping:
        for table in doc.xpath("//table"):
            cap = " ".join(table.xpath("string(caption)").split())
            if caption.lower() in cap.lower():
                villages = [
                    tidy_village(" ".join(tr.xpath("string(./td[2])").split()))
                    for tr in table.xpath(".//tbody/tr")
                    if tr.xpath("./td[2]")
                ]
                taluks.append(
                    {
                        "name": taluk_name,
                        "headquarters": hqs[taluk_name],
                        "villages": [v for v in villages if v],
                    }
                )
                break
    return taluks


def extract_pathanamthitta_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    mapping = [
        ("Adoor", "Adoor Taluk"),
        ("Kozhencherry", "Kozhencherry Taluk"),
        ("Ranni", "Ranni Taluk"),
        ("Mallappally", "Mallappally Taluk"),
        ("Thiruvalla", "Thiruvalla Taluk"),
        ("Konni", "Konni Taluk"),
    ]
    taluks = []
    for taluk_name, caption in mapping:
        for table in doc.xpath("//table"):
            cap = " ".join(table.xpath("string(caption)").split())
            if caption.lower() in cap.lower():
                villages = [
                    tidy_village(" ".join(tr.xpath("string(./td[1])").split()))
                    for tr in table.xpath(".//tbody/tr")
                    if tr.xpath("./td[1]")
                ]
                taluks.append(
                    {
                        "name": taluk_name,
                        "headquarters": hqs[taluk_name],
                        "villages": [v for v in villages if v],
                    }
                )
                break
    return taluks


def extract_kollam_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    mapping = [
        ("Kollam", "Kollam Taluk"),
        ("Kottarakkara", "Kottarakkara Taluk"),
        ("Pathanapuram", "Pathanapuram Taluk"),
        ("Karunagappally", "Karunagappally Taluk"),
        ("Kunnathur", "Kunnathur Taluk"),
        ("Punalur", "Punalur Taluk"),
    ]
    taluks = []
    for taluk_name, heading in mapping:
        for h2 in doc.xpath("//h2"):
            htxt = " ".join(h2.xpath("string(.)").split())
            if htxt.lower() == heading.lower():
                ol = h2.xpath("following::ol[1]")
                villages = [
                    tidy_village(" ".join(li.xpath("string(.)").split()))
                    for li in ol[0].xpath("./li")
                ]
                taluks.append(
                    {
                        "name": taluk_name,
                        "headquarters": hqs[taluk_name],
                        "villages": [v for v in villages if v],
                    }
                )
                break
    return taluks


def extract_thiruvananthapuram_taluks(url: str, hqs: dict[str, str]) -> list[dict]:
    doc = fetch_html(url)
    by_taluk: dict[str, list[str]] = defaultdict(list)
    name_map = {
        "Thiruvananthapuram": "Thiruvananthapuram",
        "Neyyattinkara": "Neyyattinkara",
        "Nedumangadu": "Nedumangad",
        "Kattakada": "Kattakada",
        "Chirayinkeezhu": "Chirayinkeezhu",
        "Varkala": "Varkala",
    }
    for tr in doc.xpath("//table//tbody/tr"):
        cells = [" ".join(c.xpath("string(.)").split()) for c in tr.xpath("./td")]
        if len(cells) >= 2 and cells[0] in name_map and cells[1]:
            by_taluk[name_map[cells[0]]].append(tidy_village(cells[1]))

    order = [
        "Thiruvananthapuram",
        "Neyyattinkara",
        "Nedumangad",
        "Kattakada",
        "Chirayinkeezhu",
        "Varkala",
    ]
    return [
        {
            "name": taluk_name,
            "headquarters": hqs[taluk_name],
            "villages": by_taluk[taluk_name],
        }
        for taluk_name in order
    ]


TALUK_EXTRACTORS = {
    "Kasaragod": extract_kasaragod_taluks,
    "Kannur": extract_kannur_taluks,
    "Wayanad": extract_wayanad_taluks,
    "Kozhikode": extract_kozhikode_taluks,
    "Malappuram": extract_malappuram_taluks,
    "Palakkad": extract_palakkad_taluks,
    "Ernakulam": extract_ernakulam_taluks,
    "Idukki": extract_idukki_taluks,
    "Kottayam": extract_kottayam_taluks,
    "Alappuzha": extract_alappuzha_taluks,
    "Pathanamthitta": extract_pathanamthitta_taluks,
    "Kollam": extract_kollam_taluks,
    "Thiruvananthapuram": extract_thiruvananthapuram_taluks,
}


# ---------- LSGD directory & CityPopulation extractors ----------


def fetch_lsgd_local_government(client: httpx.Client, lsgd_code: int) -> dict:
    bodies: dict[str, str] = {}
    page = 0
    while True:
        url = f"https://lsgkerala.gov.in/en/website/input/{lsgd_code}/0?page=%2C%2C%2C%2C{page}"
        response = client.get(url)
        doc = html.fromstring(response.text)
        found = 0
        for table in doc.xpath("//table"):
            trs = [
                [" ".join(c.xpath("string(.)").split()) for c in tr.xpath("./td | ./th")]
                for tr in table.xpath(".//tr")
            ]
            trs = [row for row in trs if row and any(row)]
            if trs and any("Code" in c for c in trs[0]):
                for row in trs[1:]:
                    if len(row) >= 3 and row[2] not in bodies:
                        bodies[row[2]] = row[1]
                        found += 1
        if found == 0:
            break
        page += 1

    district_panchayats = [
        display_name(name.removesuffix(" District Panchayat"))
        for code, name in bodies.items()
        if code.startswith("D")
    ]
    blocks = {
        code[3:5]: display_name(name.removesuffix(" Block Panchayat"))
        for code, name in bodies.items()
        if code.startswith("B")
    }
    gps_by_block: dict[str, list[str]] = defaultdict(list)
    for code, name in bodies.items():
        if code.startswith("G"):
            gps_by_block[code[3:5]].append(display_name(name.removesuffix(" Grama Panchayat")))

    block_profiles = []
    for bcode, bname in sorted(blocks.items(), key=lambda item: item[1]):
        gps = sorted(gps_by_block[bcode])
        if not gps:
            raise RuntimeError(f"Block {bname} ({bcode}) has no gram panchayats")
        block_profiles.append({"name": bname, "gram_panchayats": gps})

    municipalities = sorted(
        display_name(name.removesuffix(" Municipality"))
        for code, name in bodies.items()
        if code.startswith("M")
    )
    corporations = sorted(
        display_name(name.removesuffix(" Corporation"))
        for code, name in bodies.items()
        if code.startswith("C")
    )

    return {
        "district_panchayat": district_panchayats[0] if district_panchayats else "",
        "blocks": block_profiles,
        "municipalities": municipalities,
        "municipal_corporations": corporations,
    }


def fetch_demographics(client: httpx.Client, cp_admin_slug: str) -> dict:
    url = f"https://www.citypopulation.de/en/india/kerala/admin/{cp_admin_slug}/"
    doc = html.fromstring(client.get(url).text)
    tr_dist = doc.xpath("//table[@id='tl']//tbody/tr[1]")[0]
    area = int(float(tr_dist.xpath("./td[1]/@data-area")[0]))
    density = round(float(tr_dist.xpath("./td[1]/@data-density")[0]))
    pop = int(tr_dist.xpath("string(./td[3])").replace(",", "").strip())

    kv: dict[str, int] = {}
    for tr in doc.xpath("//table//tr"):
        cells = [" ".join(c.xpath("string(.)").split()) for c in tr.xpath("./td")]
        if len(cells) == 2 and cells[0] in ("males", "females", "rural", "urban", "yes", "no"):
            kv[cells[0]] = int(cells[1].replace(",", ""))

    return {
        "area_km2": area,
        "population": pop,
        "population_year": 2011,
        "density_per_km2": density,
        "literacy_rate": round(kv["yes"] * 100 / (kv["yes"] + kv["no"]), 2),
        "sex_ratio": round(kv["females"] * 1000 / kv["males"]),
        "urban_share": round(kv["urban"] * 100 / (kv["rural"] + kv["urban"]), 2),
    }


def fetch_towns(
    client: httpx.Client,
    district: str,
    cp_town_slug: str,
    municipalities: list[str],
    corporations: list[str],
) -> list[dict]:
    url = f"https://www.citypopulation.de/en/india/kerala/{cp_town_slug}/"
    doc = html.fromstring(client.get(url).text)

    muni_set = set(municipalities)
    corp_set = set(corporations)

    towns_by_key: dict[tuple[str, str], dict] = {}
    seen_munis: set[str] = set()
    seen_corps: set[str] = set()

    for tr in doc.xpath("//table[@id='ts']//tbody/tr"):
        cells = [" ".join(c.xpath("string(.)").split()) for c in tr.xpath("./td")]
        if not cells or not cells[0]:
            continue
        raw_name = re.sub(r"\s*\([^)]*\)$", "", cells[0]).strip()
        raw_name = re.sub(r"\s*\[[^\]]*\]$", "", raw_name).strip()
        raw_status = cells[1]
        pop = int(cells[5].replace(",", ""))

        # Special case: North Paravur in Ernakulam is listed as "Paravur" in CP
        if district == "Ernakulam" and raw_name == "Paravur":
            name = "North Paravur"
        elif district == "Palakkad" and raw_name == "Chittur-Thathamangalam":
            name = "Chittur Tattamangalam"
        elif district == "Palakkad" and raw_name == "Mannarkad-I":
            name = "Mannarkad"
        else:
            name = display_name(raw_name)

        if name in corp_set and (
            "Corporation" in raw_status or name not in seen_corps
        ):
            status = "Municipal corporation"
            seen_corps.add(name)
        elif name in muni_set and (
            "Municipality" in raw_status or name not in seen_munis
        ):
            if name in seen_munis:
                # e.g., Perumbavoor (Municipality) and Perumbavoor (Census Town)
                status = "Census town"
                name = f"{name} (CT)"
            else:
                status = "Municipality"
                seen_munis.add(name)
        else:
            status = "Census town"

        towns_by_key[(name, status)] = {
            "name": name,
            "population_2011": pop,
            "status": status,
        }

    # Add post-2011 municipalities that were rural panchayats in the 2011 town table
    for muni in municipalities:
        if muni not in seen_munis:
            pop = MUNICIPALITY_POP_2011.get((district, muni))
            if pop is None:
                raise RuntimeError(f"Missing 2011 population for municipality {muni} ({district})")
            towns_by_key[(muni, "Municipality")] = {
                "name": muni,
                "population_2011": pop,
                "status": "Municipality",
            }

    return sorted(towns_by_key.values(), key=lambda item: item["name"])


def load_assembly_seats_by_district() -> dict[str, list[int]]:
    seats: dict[str, list[int]] = defaultdict(list)
    with RESULTS_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if int(row["election_year"]) == 2026:
                seats[row["district"]].append(int(row["ac_no"]))
    return {district: sorted(ac_nos) for district, ac_nos in seats.items()}


def main() -> int:
    existing = {}
    if DISTRICT_DETAILS_JSON.exists():
        existing = json.loads(DISTRICT_DETAILS_JSON.read_text(encoding="utf-8"))

    seats_by_district = load_assembly_seats_by_district()
    profiles: dict[str, dict] = {}

    with httpx.Client(
        transport=httpx.HTTPTransport(retries=3),
        follow_redirects=True,
        timeout=30,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for district, spec in DISTRICT_SPECS.items():
            # Preserve the hand-curated Thrissur profile unchanged
            if district == "Thrissur" and "Thrissur" in existing:
                print("Keeping existing Thrissur profile...")
                profiles["Thrissur"] = existing["Thrissur"]
                continue

            print(f"Building profile for {district}...")
            taluks = TALUK_EXTRACTORS[district](spec["portal_url"], spec["taluk_hqs"])
            local_gov = fetch_lsgd_local_government(client, spec["lsgd_code"])
            demographics = fetch_demographics(client, spec["cp_admin_slug"])
            towns = fetch_towns(
                client,
                district,
                spec["cp_town_slug"],
                local_gov["municipalities"],
                local_gov["municipal_corporations"],
            )

            profiles[district] = {
                "district": district,
                "retrieved": RETRIEVED_DATE,
                "summary": spec["summary"],
                "demographics": demographics,
                "revenue_divisions": spec["revenue_divisions"],
                "taluks": taluks,
                "local_government": local_gov,
                "towns": towns,
                "assembly_seats": seats_by_district[district],
                "parliamentary_seats": spec["parliamentary_seats"],
                "sources": [
                    {
                        "label": f"{district} district portal — taluks and revenue villages",
                        "short": "District portal",
                        "url": spec["portal_url"],
                    },
                    {
                        "label": (
                            "LSGD local-body directory — current block and gram panchayat codes"
                        ),
                        "short": "LSGD directory",
                        "url": "https://lsgkerala.gov.in/en/website/web",
                    },
                    {
                        "label": "Census 2011 towns and populations",
                        "short": "Census 2011",
                        "url": f"https://www.citypopulation.de/en/india/kerala/{spec['cp_town_slug']}/",
                    },
                    {
                        "label": "Revenue divisions, taluk headquarters and seats (Wikipedia)",
                        "short": "Wikipedia",
                        "url": f"https://en.wikipedia.org/w/index.php?title={spec['wiki_title']}&oldid={spec['wiki_oldid']}",
                    },
                ],
            }
            v_count = sum(len(t["villages"]) for t in taluks)
            gp_count = sum(len(b["gram_panchayats"]) for b in local_gov["blocks"])
            print(
                f"  {len(taluks)} taluks, {v_count} villages, "
                f"{len(local_gov['blocks'])} blocks, {gp_count} GPs, "
                f"{len(local_gov['municipalities'])} munis, {len(towns)} towns"
            )

    DISTRICT_DETAILS_JSON.write_text(
        json.dumps(profiles, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {DISTRICT_DETAILS_JSON.name} with {len(profiles)} districts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

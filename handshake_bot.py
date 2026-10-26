import json
import logging
import os
import re
import markdown
import google.generativeai as genai
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()  # .env dosyasını oku (GEMINI_API_KEY, HANDSHAKE_SEARCH_ID)

# --- AYARLAR ---
BASE = "https://app.joinhandshake.com"
LOGIN_URL = f"{BASE}/login"
SEARCH_ID = os.environ.get("HANDSHAKE_SEARCH_ID", "")  # Kendi Handshake ilan aramanın ID'si (.env içinde)
SEARCH_URL = f"{BASE}/job-search/{SEARCH_ID}?page=1&per_page=25"
MAX_CANDIDATES = 25          # Quick Apply bulmak için en fazla kaç ilan taransın
APPLY_CONFIRM_TIMEOUT = 30   # Submit sonrası "Withdraw application" çıkana kadar en fazla bekleme (sn)
DEBUG_DIR = "debug"
os.makedirs(DEBUG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(), logging.FileHandler("job_bot.log", encoding="utf-8")],
)

# API anahtarı .env dosyasından okunur (GEMINI_API_KEY=...). Anahtarı koda yazma.
API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not API_KEY:
    raise SystemExit("GEMINI_API_KEY tanımlı değil: .env dosyası oluştur ve GEMINI_API_KEY=anahtarın satırını ekle.")
if not SEARCH_ID:
    raise SystemExit("HANDSHAKE_SEARCH_ID tanımlı değil: .env dosyasına HANDSHAKE_SEARCH_ID=ilan_arama_id_si satırını ekle.")
genai.configure(api_key=API_KEY)

_step_no = 0


def step(page, name):
    """Her adımı loglar ve ekran görüntüsü alır (debug/ klasörü)."""
    global _step_no
    _step_no += 1
    shot = f"{DEBUG_DIR}/{_step_no:02d}_{re.sub(r'[^a-zA-Z0-9]+', '_', name)[:40]}.png"
    logging.info(f"➡️  ADIM {_step_no}: {name}")
    try:
        page.screenshot(path=shot)
    except Exception as e:
        logging.warning(f"Ekran görüntüsü alınamadı: {e}")


# --- AI KISMI ---
MAX_TRIES = 3  # AI çıktısı doğrulamadan geçmezse en fazla kaç kez yeniden denensin

# Master CV'de yoksa CV/ön yazıda GEÇMEMESİ gereken teknoloji adları
TECH_TERMS = [
    "react", "angular", "vue", "node.js", "nodejs", "django", "flask", "spring", "sql", "mysql",
    "postgresql", "mongodb", "aws", "azure", "gcp", "docker", "kubernetes", "typescript", "php",
    "ruby", "swift", "rust", "scala", "tensorflow", "pytorch", "firebase", "supabase", "unreal",
    "jira", "figma", "selenium", "jenkins", "tailwind", "next.js", "express.js", "expressjs", "laravel", "asp.net",
    ".net", "html", "css", "graphql", "redis", "linux", "agile", "scrum", "ci/cd", "microservices",
    "rest api", "machine learning", "deep learning", "pandas", "numpy", "excel", "photoshop",
]
# Master CV'de yoksa yasak olan abartı/uydurma ifadeler
BANNED_PHRASES = [
    "workflow automation", "systems integration", "api/systems", "scalable", "production-ready",
    "production ready", "responsive", "ecosystem", "web-oriented", "clean ui", "data handling",
    "user flows", "interface structures", "full technical ownership", "seamless", "cutting-edge",
    "passionate", "expert", "proven track record", "results-driven", "spearheaded", "leveraged",
    "robust", "state-of-the-art", "perfect fit",
]


# --- FİLTRE: IT / yazılım / donanım / veri / AI / siber güvenlik / teknik destek vb. HER ŞEY ---
# Kısa kısaltmalar (AI, IT, QA...) kelime sınırıyla aranır; "email", "retail", "opportunity" gibi kelimelere takılmaz.
ACRONYMS = [
    "AI", "A.I.", "ML", "IT", "QA", "QE", "SDET", "SWE", "SDE", "UX", "UI", "SRE", "ETL", "BI", "NLP", "LLM", "LLMs",
    "GPT", "RPA", "CI/CD", "API", "APIs", "SDK", "SaaS", "PaaS", "IaaS", "IoT", "VR", "XR", "NOC", "SOC", "SIEM",
    "SOAR", "EDR", "GRC", "HPC", "GPU", "FPGA", "VLSI", "RTL", "PLC", "SCADA", "ERP", "CRM", "SAP", "EDA", "DSP",
    "MCU", "RTOS", "AWS", "GCP", "PHP", "SQL", "NoSQL", "Rust", "Dart", "Unity", "Unreal", "Swift", "React",
    "Scala", "Git", "iOS", "GIS", "MIS", "DevOps", "MLOps", "AIOps", "DataOps", "M365", "O365", "VPN", "DNS",
    "TCP/IP", "LAN", "WAN", "SD-WAN", "MSP", "MSSP", "CMMC", "NIST", "HIPAA", "ISO 27001", "SOC 2",
]
_ACR = "|".join(re.escape(a) for a in sorted(set(ACRONYMS), key=len, reverse=True))
ACR_CS = re.compile(rf"(?<![A-Za-z0-9])(?:{_ACR})(?![A-Za-z0-9])")          # ilan açıklaması: büyük/küçük harf duyarlı
ACR_CI = re.compile(rf"(?<![A-Za-z0-9])(?:{_ACR})(?![A-Za-z0-9])", re.I)    # başlık: duyarsız

TITLE_INCLUDE = [
    # genel yazılım / mühendislik
    "software", "developer", "development", "programmer", "programming", "coder", "coding", "engineer",
    "engineering", "full stack", "fullstack", "full-stack", "front end", "front-end", "frontend", "back end",
    "back-end", "backend", "web", "website", "application developer", "application support", "application engineer",
    "mobile", "android", "cross-platform", "cross platform", "technolog", "technical", "tech ", " tech", "computer",
    "computing", "computational", "information system", "information tech", "digital transformation", "automation",
    "scripting",
    # diller / framework
    "python", "java", "javascript", "typescript", "c#", "c++", ".net", "dotnet", "kotlin", "flutter",
    "react native", "reactjs", "angular", "vue", "node", "django", "flask", "spring boot", "golang", "ruby",
    "perl", "matlab", "solidity", "godot", "wordpress", "shopify", "salesforce", "servicenow", "sharepoint",
    "power apps", "power platform", "power bi", "tableau", "looker", "dynamics", "microsoft 365",
    # oyun / grafik / XR
    "game", "gameplay", "graphics", "rendering", "simulation", "3d", "virtual reality", "augmented reality",
    # donanım / gömülü / elektronik
    "hardware", "embedded", "firmware", "electronic", "electrical", "circuit", "pcb", "semiconductor", "robot",
    "mechatronic", "control systems", "instrumentation", "telecom", "wireless", "network", "signal processing",
    "drone", "uav", "autonomous", "avionics", "autocad", "solidworks",
    # veri / AI
    "data", "analytics", "data analy", "systems analyst", "it analyst", "security analyst", "technical analyst",
    "business systems", "business intelligence", "big data", "database", "machine learning", "machine-learning",
    "deep learning", "artificial intelligence", "generative", "genai", "computer vision", "prompt", "chatbot",
    "conversational", "neural", "statistic", "quantitative", "research engineer", "research scientist",
    "research software", "ai research", "ml research", "computer science", "bioinformatics", "geospatial",
    "remote sensing",
    # bulut / altyapı / sistem
    "cloud", "devops", "devsecops", "site reliability", "platform", "infrastructure", "systems", "system admin",
    "sysadmin", "system administrator", "network administrator", "database administrator", "kubernetes", "docker",
    "linux", "windows", "azure", "virtualization", "build engineer", "systems integration", "migration",
    # güvenlik
    "cyber", "security", "infosec", "penetration", "pentest", "red team", "blue team", "threat", "vulnerability",
    "malware", "forensic", "incident response", "access management",
    # test / destek / danışmanlık
    "quality assurance", "tester", "testing", "test ", "help desk", "helpdesk", "service desk", "desktop support",
    "technical support", "support engineer", "support specialist", "support analyst", "support technician",
    "it support", "solutions architect", "solution architect", "solutions engineer", "software architect",
    "cloud architect", "enterprise architect", "data architect", "security architect", "it consultant",
    "technology consultant", "technical consultant", "implementation engineer", "implementation specialist",
    "customer engineer", "sales engineer", "technical account", "technical writer", "technical writing",
    # ürün / tasarım / proje (teknoloji tarafı)
    "product manager", "product analyst", "product owner", "product management", "technical project",
    "technical program", "it project", "scrum", "agile", "ui/ux", "user experience", "user interface",
    "product designer", "web designer", "interaction design", "low-code", "no-code",
    # diğer
    "blockchain", "web3", "crypto", "fintech", "healthtech", "edtech",
]

DESC_INCLUDE = [
    # genel
    "software", "developer", "programming", "coding", "computer science", "information technology",
    "information systems", "computer engineering", "software engineering", "web development", "mobile app",
    "mobile development", "application development", "full stack", "full-stack", "frontend", "front-end",
    "backend", "back-end", "scripting", "algorithm", "data structures", "object-oriented", "debugging",
    "troubleshooting", "technical support", "it support", "help desk", "helpdesk", "service desk", "sysadmin",
    "system administration", "systems administration", "network administration", "network engineer",
    "desktop support", "endpoint", "patching", "test automation", "process automation", "workflow automation",
    "it automation",
    # diller / framework / araçlar
    "python", "java", "javascript", "typescript", "c#", "c++", ".net", "dotnet", "kotlin", "flutter",
    "react native", "reactjs", "react.js", "angular", "node.js", "nodejs", "django", "flask", "spring boot",
    "golang", "ruby", "php", "android", "godot", "matlab", "bash", "powershell", "sql", "nosql", "mongodb",
    "postgres", "mysql", "firebase", "supabase", "graphql", "rest api", "restful", "microservice", "github",
    "gitlab", "docker", "kubernetes", "terraform", "ansible", "jenkins", "ci/cd", "linux", "unix",
    "windows server", "active directory", "entra id", "azure", "aws", "gcp", "google cloud", "microsoft 365",
    "office 365", "sharepoint", "power bi", "tableau", "looker", "salesforce", "servicenow", "power apps",
    "power automate", "low-code", "no-code", "wordpress", "autocad", "solidworks",
    # veri / AI
    "machine learning", "deep learning", "artificial intelligence", "generative ai", "genai", "llm",
    "large language model", "neural network", "natural language processing", "computer vision", "tensorflow",
    "pytorch", "pandas", "numpy", "data analysis", "data analytics", "data science", "data engineering",
    "data visualization", "data pipeline", "business intelligence", "big data", "predictive model", "ai/ml",
    "ai tools", "ai-powered", "ai-driven", "prompt engineering", "chatbot",
    # donanım / gömülü
    "hardware", "embedded systems", "embedded software", "firmware", "electronics", "pcb", "fpga",
    "microcontroller", "arduino", "raspberry pi", "robotics", "internet of things", "semiconductor",
    "telecommunications", "signal processing",
    # güvenlik / ağ
    "cybersecurity", "cyber security", "information security", "network security", "infosec",
    "penetration test", "vulnerability", "malware", "incident response", "firewall", "tcp/ip", "siem",
    "soc analyst", "security operations", "endpoint detection", "multi-factor", "encryption",
    "compliance framework",
    # ürün / test / diğer
    "quality assurance", "unit test", "selenium", "ui/ux", "user interface", "user experience", "figma",
    "scrum", "technical documentation", "blockchain", "web3", "game development", "gameplay",
    "digital transformation",
]


def _hit(title, description):
    """İlk eşleşen terimi döndürür (loglamak için), yoksa None."""
    tl, dl = title.lower(), description.lower()
    for k in TITLE_INCLUDE:
        if k in tl:
            return f"başlık: '{k.strip()}'"
    m = ACR_CI.search(title)
    if m:
        return f"başlık: '{m.group(0)}'"
    for k in DESC_INCLUDE:
        if k in dl:
            return f"açıklama: '{k}'"
    m = ACR_CS.search(description)
    if m:
        return f"açıklama: '{m.group(0)}'"
    return None


def is_software_job(title, description):
    """Başlık VEYA açıklamada herhangi bir IT/yazılım/donanım/veri/AI/güvenlik terimi varsa True."""
    h = _hit(title, description)
    if h:
        logging.info(f"  ✔ Filtre eşleşti ({h})")
        return True
    return False


def ask_ai(prompt):
    cfg = {"temperature": 0.2}
    models = [
        "gemini-3.5-flash-lite",  # eskiden kullandığımız, hızlı: önce bu
        "gemini-3.5-flash",
        "gemini-3-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
    ]
    for model in models:
        try:
            logging.info(f"🧠 Model: {model}")
            return genai.GenerativeModel(model).generate_content(
                prompt, generation_config=cfg, request_options={"timeout": 90}
            ).text
        except Exception as e:
            if model == models[-1]:
                logging.error(f"❌ Tüm modeller başarısız: {e}")
                raise
            logging.warning(f"⚠️ {model} başarısız/zaman aşımı ({str(e)[:80]}). Sonrakine geçiliyor...")


def load_master():
    with open("master_cv.json", "r", encoding="utf-8") as f:
        raw = f.read()
    return raw, json.loads(raw)


def norm(s):
    """Karşılaştırma için metni sadeleştirir (tire türleri, boşluk, **, sondaki nokta)."""
    s = s.replace("—", "-").replace("–", "-").replace("**", "").replace("`", "")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s.rstrip(".")


def normalize_md(md):
    """AI çıktısını temizler: kod çiti, madde işaretleri, liste/başlık öncesi-sonrası boş satır."""
    md = md.replace("\r\n", "\n").strip()
    md = re.sub(r"^```[a-zA-Z]*\s*\n", "", md)
    md = re.sub(r"\n```\s*$", "", md)
    out = []
    for line in md.split("\n"):
        s = line.strip()
        if not s:
            if out and out[-1] != "":
                out.append("")
            continue
        if re.match(r"[-*•]\s+", s):
            item = "- " + re.sub(r"^[-*•]\s+", "", s)
            if out and out[-1] != "" and not out[-1].startswith("- "):
                out.append("")
            out.append(item)
        elif s.startswith("#"):
            if out and out[-1] != "":
                out.append("")
            out.append(s)
            out.append("")
        else:
            if out and out[-1].startswith("- "):
                out.append("")
            out.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def term_in(term, text):
    return re.search(rf"(?<![a-z0-9+#.]){re.escape(term)}(?![a-z0-9+#])", text) is not None


FUNCTION_WORDS = set("""a an the and or of in on at to for with by from as is are was were be been being that this these those
it its their his her which who whom while also both into over under across through using use used within without between
more most such than then thus so but not no can will has have had i we our my you your""".split())


def _stem(w):
    for suf in ("ing", "ed", "es", "s", "ly"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _words(text):
    return [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", text) if len(w) >= 2]


def unknown_words(text, master_raw):
    """text içindeki, master'da (kelime/kök olarak) ve temel bağlaç listesinde olmayan kelimeler."""
    vocab = set(_words(master_raw))
    stems = {_stem(w) for w in vocab}
    bad = []
    for w in _words(text):
        if w in vocab or w in FUNCTION_WORDS or _stem(w) in stems:
            continue
        if w not in bad:
            bad.append(w)
    return bad


def novel_terms(md, master_raw, extra_ok=()):
    """Araç/teknoloji gibi görünen (özel isim, kısaltma, CamelCase, c++/node.js) ama master'da olmayan terimler."""
    text = re.sub(r"\(https?://[^)]*\)", "", md).replace("**", "")
    text = re.sub(r"\S+@\S+", "", text)
    text = "\n".join(l for l in text.split("\n") if not l.startswith("# ") and not l.startswith("## "))
    ok = set(_words(master_raw)) | {w for x in extra_ok for w in _words(x)} | FUNCTION_WORDS
    found = []

    mlow = master_raw.lower()

    def add(tok):
        t = tok.lower().strip(".")
        if t in ok or (re.search(r"[#+.]", tok) and t in mlow):
            return
        if tok not in found:
            found.append(tok)

    for tok in re.findall(r"\b[A-Za-z]+(?:[#+]{1,2})|\b[A-Za-z]{2,}\.[A-Za-z]{2,}\b|\B\.[A-Za-z]+\b", text):
        add(tok)
    for tok in re.findall(r"\b[A-Z]{2,}[a-z]*\b", text):          # SQL, API, AWS
        add(tok)
    for tok in re.findall(r"\b[A-Z][a-z]+[A-Z][A-Za-z]+\b", text):  # PostgreSQL, TensorFlow
        add(tok)
    for sent in re.split(r"(?<=[.!?])\s+|\n", text):               # cümle ortasında büyük harfli kelimeler
        sent = re.sub(r"^[-\s]+", "", sent)
        for tok in re.findall(r"[A-Za-z][A-Za-z\-]+", sent)[1:]:
            if tok[0].isupper():
                add(tok)
    return [f"Master'da olmayan olası araç/özel isim: '{t}'" for t in found]


def validate_common(md, master_raw, extra_ok=()):
    """CV ve ön yazı için ortak kontroller: master'da olmayan teknoloji / abartı / sayı / placeholder."""
    problems = []
    low, mlow = md.lower(), master_raw.lower()
    for t in TECH_TERMS:
        if term_in(t, low) and not term_in(t, mlow):
            problems.append(f"Master'da olmayan teknoloji/araç geçiyor: '{t}'")
    for ph in BANNED_PHRASES:
        if ph in low and ph not in mlow:
            problems.append(f"Master'da olmayan abartılı/uydurma ifade: '{ph}'")
    extra = set(re.findall(r"\d+", md)) - set(re.findall(r"\d+", master_raw))
    if extra:
        problems.append(f"Master'da olmayan sayı/tarih: {sorted(extra)}")
    if re.search(r"\[[^\]]*\](?!\()", md):
        problems.append("Metinde köşeli parantezli placeholder var")
    problems += novel_terms(md, master_raw, extra_ok)
    return problems


def allowed_bullets(master):
    allowed = set()
    for e in master["experience"]:
        allowed.update(norm(b) for b in e["bullets"])
    for p in master["projects"]:
        allowed.update(norm(b) for b in p.get("bullets", []))
        allowed.update(norm(i) for i in p.get("items", []))
    allowed.update(norm(c) for c in master.get("certifications", []))
    return allowed


def validate_cv(md, master, master_raw):
    problems = validate_common(md, master_raw)
    summ = re.search(r"## Professional Summary\s*(.*?)(?=\n## )", md, re.S)
    if summ:
        unk = unknown_words(summ.group(1), master_raw)
        if unk:
            problems.append(f"Özette master'da geçmeyen kelimeler: {unk}")
    else:
        problems.append("Özet bölümü bulunamadı")
    n = norm(md)
    # 1) Tüm deneyimler (rol, şirket, tarih, her madde birebir) mutlaka olmalı
    for e in master["experience"]:
        for key in ("role", "company", "dates"):
            if norm(e[key]) not in n:
                problems.append(f"Eksik: {e['company']} → {key} ('{e[key]}')")
        for b in e["bullets"]:
            if norm(b) not in n:
                problems.append(f"{e['company']} maddesi birebir yok: '{b[:60]}...'")
    # 2) Projeler: bullets'lı tüm projeler (başlık + her madde birebir) ve 'items'lı grup (4-6 madde)
    for pr in master["projects"]:
        if norm(pr["name"]) not in n:
            problems.append(f"Proje başlığı eksik: {pr['name']}")
        for b in pr.get("bullets", []):
            if norm(b) not in n:
                problems.append(f"{pr['name']} maddesi birebir yok: '{b[:60]}...'")
        if "items" in pr:
            used = sum(1 for i in pr["items"] if norm(i) in n)
            if not 4 <= used <= 6:
                problems.append(f"Ek projelerden {used} adet var (4-6 olmalı)")
    # 3) Her 'madde' master'daki bir maddeyle birebir aynı olmalı (beceri satırları hariç)
    allowed = allowed_bullets(master)
    for line in md.split("\n"):
        if line.startswith("- ") and not line.startswith("- **"):
            if norm(line[2:]) not in allowed:
                problems.append(f"Master'da olmayan madde: '{line[2:70]}...'")
    # 4) Beceri satırlarında yalnızca master'daki beceriler
    sk = master["skills"]
    known = {norm(x) for k in ("programming_languages", "frameworks_and_platforms", "other_skills", "spoken_languages") for x in sk[k]}
    for line in md.split("\n"):
        if re.match(r"- \*\*(Programming Languages|Frameworks & Platforms|Other Skills|Spoken Languages):\*\*", line):
            for tok in line.split(":**", 1)[1].split(","):
                if tok.strip() and norm(tok) not in known:
                    problems.append(f"Master'da olmayan beceri: '{tok.strip()}'")
    for x in sk["programming_languages"] + sk["frameworks_and_platforms"]:
        if norm(x) not in n:
            problems.append(f"Beceri eksik: {x}")
    return problems


def validate_cl(md, master, master_raw, extra_ok=()):
    body = re.sub(r"^(Dear Hiring Team,|Sincerely,)\s*$", "", md, flags=re.M)
    problems = validate_common(body, master_raw, extra_ok)
    words = len(md.split())
    if not 120 <= words <= 260:
        problems.append(f"Kelime sayısı uygun değil: {words} (120-260 olmalı)")
    if master["name"].lower() not in md.lower():
        problems.append("Ad-soyad imzada yok")
    if re.search(r"^#|^- ", md, re.M):
        problems.append("Başlık/liste kullanılmış (sadece paragraf olmalı)")
    return problems


def generate_validated(prompt, assemble, validate):
    """AI'ı çağırır, çıktıyı doğrular; sorun varsa geri bildirimle yeniden dener."""
    problems, full = [], ""
    for attempt in range(1, MAX_TRIES + 1):
        p = prompt
        if problems:
            fb = "\n".join(f"- {x}" for x in problems[:15])
            p += f"\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED FOR THESE VIOLATIONS. FIX ALL OF THEM AND FOLLOW EVERY RULE:\n{fb}\n"
        full = assemble(normalize_md(ask_ai(p)))
        problems = validate(full)
        if not problems:
            logging.info(f"✅ Doğrulama geçti (deneme {attempt}).")
            return full, []
        logging.warning(f"❌ Doğrulama başarısız (deneme {attempt}/{MAX_TRIES}): {len(problems)} sorun")
        for x in problems[:10]:
            logging.warning(f"   - {x}")
    return full, problems


CV_CSS = """
body { font-family: Helvetica, Arial, sans-serif; line-height: 1.35; color: #222; margin: 0; font-size: 11px; }
h1 { border-bottom: 2px solid #333; padding-bottom: 4px; font-size: 22px; color: #000; text-align: center; margin: 0 0 4px 0; }
h2 { border-bottom: 1px solid #bbb; padding-bottom: 2px; font-size: 13px; color: #111; margin: 10px 0 4px 0; text-transform: uppercase; }
h3 { font-size: 11.5px; margin: 6px 0 2px 0; }
p { margin: 3px 0; }
ul { margin: 2px 0 2px 0; padding-left: 18px; }
li { margin-bottom: 2px; }
"""
CL_CSS = "body { font-family: Helvetica, Arial, sans-serif; line-height: 1.55; color: #333; margin: 0; font-size: 13px; } p { margin: 14px 0; }"


def render_pdf(context, md_text, path, css, margin, one_page=False):
    html = f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>{markdown.markdown(md_text)}</body></html>"
    pg = context.new_page()
    pg.set_content(html)
    scales = [1.0, 0.93, 0.86, 0.8] if one_page else [1.0]
    data, pages = b"", 0
    for sc in scales:
        data = pg.pdf(format="A4", margin=margin, scale=sc, print_background=True)
        pages = len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", data))
        if pages <= 1:
            break
    pg.close()
    with open(path, "wb") as f:
        f.write(data)
    logging.info(f"📄 {path} oluşturuldu ({pages} sayfa, ölçek {sc}).")
    if one_page and pages > 1:
        logging.warning("⚠️ CV tek sayfaya sığmadı.")


# --- CV ---
def build_header_md(m):
    c = m["contact"]
    return f"# {m['name']}\n\n{c['location']} | {c['email']} | [LinkedIn]({c['linkedin']}) | [GitHub]({c['github']})\n"


def build_tail_md(m):
    lines = ["## Education", ""]
    for e in m["education"]:
        lines += [f"**{e['school']}** — {e['location']} | {e['dates']}", "", e["degree"], ""]
    if m.get("certifications"):
        lines += ["## Certifications", ""] + [f"- {c}" for c in m["certifications"]]
    return "\n".join(lines) + "\n"


def assemble_cv(m, body_md):
    spoken = ", ".join(m["skills"]["spoken_languages"])
    body = re.sub(r"\n+(## Professional Experience)", lambda mo: f"\n- **Spoken Languages:** {spoken}\n\n{mo.group(1)}", body_md, count=1)
    for pr in m["projects"]:
        if pr.get("link") and "bullets" in pr:
            disp = re.sub(r"^https?://|/$", "", pr["link"])
            body = re.sub(rf"^### {re.escape(pr['name'])}\s*$", f"### {pr['name']} | [{disp}]({pr['link']})", body, flags=re.M)
    return build_header_md(m) + "\n" + body.strip() + "\n\n" + build_tail_md(m)


CV_STRUCTURE = """## Professional Summary

<2-3 sentences>

## Technical Skills

- **Programming Languages:** <comma-separated>
- **Frameworks & Platforms:** <comma-separated>
- **Other Skills:** <comma-separated>

## Professional Experience

### <Role> — <Company> | <dates>

- <bullet copied exactly>
- <bullet copied exactly>

(repeat for EVERY role in the master, same order as the master)

## Projects

### <Featured project name exactly as in master>

- <bullet copied exactly>
- <bullet copied exactly>

(repeat for EVERY master project that has "bullets")

### Additional Independent Projects (C#)

- <item copied exactly>
(4 to 6 items)"""


def generate_cv_pdf(job_title, job_description, context, is_sw):
    """Döndürür: doğrulama sorunları listesi (boşsa temiz)."""
    logging.info("🧠 AI: İlana özel CV hazırlanıyor (katı mod)...")
    master_raw, master = load_master()
    if is_sw:
        focus = ("The job is software/IT related. Order skills and the 4-6 additional projects so that the ones most "
                 "relevant to the posting come first. Keep the summary factual.")
    else:
        focus = ("The job is NOT software related. Do NOT add any soft-skill claims that are not in the master. "
                 "In the summary, state only factual master content (student status, independent delivery of projects, "
                 "adoption of work by a university and a studio, English level). Put the most accessible projects first.")
    prompt = f"""You are a meticulous résumé EDITOR, not a writer. You NEVER create new content. You only SELECT and REORDER
content that already exists in the MASTER CV (JSON) so that it fits the JOB POSTING.

ABSOLUTE RULES (any violation makes your output unusable and it will be rejected automatically):
1. SOURCE OF TRUTH: every fact, tool, technology, skill, number, date, employer, title and claim MUST come from the MASTER CV.
   The JOB POSTING is ONLY a guide for ordering/emphasis. NEVER copy a skill, tool, keyword or requirement from the posting
   into the résumé unless the exact same item already exists in the MASTER CV.
2. NO INVENTION: do not add technologies, skills, duties, achievements, metrics, adjectives or claims that are not in the MASTER CV.
   Never use words such as: scalable, responsive, seamless, production-ready, robust, expert, expertise, passionate,
   results-driven, workflow automation, systems integration, architecture, ecosystem (unless they appear in the MASTER CV).
3. BULLETS VERBATIM: copy every experience bullet, the hospital project description and every project item EXACTLY as written
   in the MASTER CV (same words, same tense). Do not paraphrase, shorten, merge, split or embellish. You may only reorder
   bullets inside the same role.
4. INCLUDE EVERY ROLE: every entry in master "experience" MUST appear, with all its bullets, in the same order as the master
   (most recent first). Never drop a role, even if it seems less relevant.
5. PROJECTS: EVERY project in master "projects" that has "bullets" MUST be included under its exact master name, with ALL of its
   bullets copied exactly. You may order those projects (and their bullets) by relevance to the posting. Do NOT add any
   website link, it is added automatically. Then add the group "Additional Independent Projects (C#)" with 4 to 6 items copied
   exactly from the master items (most relevant first). Never change that group name and never mention any language other
   than C# for it.
6. SKILLS: use ONLY items present in master "skills". Include ALL programming languages and ALL frameworks/platforms, and
   reorder them (most relevant first). "Other Skills" may only contain items from master "other_skills".
7. SUMMARY: 2-3 sentences built ONLY from the master "summary". You may reorder emphasis toward the posting, but add no new
   claim, do not mention the employer, and keep "Software Engineering student".
8. NUMBERS AND DATES: use only those that appear in the MASTER CV.
9. DO NOT output the name/contact header, Education, Certifications or Spoken Languages. They are added automatically.
10. OUTPUT: ONLY Markdown in exactly the structure below. Every bullet on its own line starting with "- ". A blank line before
    every list and after every heading. No code fences. No commentary before or after.

{focus}

REQUIRED STRUCTURE:
{CV_STRUCTURE}

[MASTER CV]:
{master_raw}

[JOB TITLE]: {job_title}
[JOB POSTING]:
{job_description[:6000]}"""
    full, problems = generate_validated(
        prompt, lambda body: assemble_cv(master, body), lambda md: validate_cv(md, master, master_raw)
    )
    with open("cv.md", "w", encoding="utf-8") as f:
        f.write(full)
    render_pdf(context, full, "cv.pdf", CV_CSS, {"top": "0.9cm", "right": "1.2cm", "bottom": "0.9cm", "left": "1.2cm"}, one_page=True)
    return problems


# --- COVER LETTER ---
def generate_cover_letter_pdf(job_title, job_description, context, employer=""):
    """Döndürür: doğrulama sorunları listesi (boşsa temiz)."""
    logging.info("🧠 AI: Ön yazı (cover letter) yazılıyor (katı mod)...")
    master_raw, master = load_master()
    employer_txt = employer or "the hiring organization"
    prompt = f"""You write a short cover letter for {master['name']} applying to the position "{job_title}" at {employer_txt}.
You may ONLY use facts from the MASTER CV (JSON). Any violation makes the output unusable and it will be rejected automatically.

ABSOLUTE RULES:
1. SOURCE OF TRUTH: every experience, project, tool, skill, number and date MUST come from the MASTER CV. Never invent experience,
   metrics, motivations, achievements or tools. Never claim a skill that the job posting asks for but the MASTER CV lacks;
   simply do not mention it.
2. Use the JOB POSTING only to decide which 1-3 facts from the MASTER CV to highlight. Do not repeat the posting's wording as
   if it were the candidate's experience.
3. Do not claim knowledge of the company beyond its name and what is explicitly written in the posting. No flattery, no
   invented mission statements.
4. Do not use: passionate, perfect fit, proven track record, expert, results-driven, cutting-edge, seamless, robust, spearheaded, leveraged.
5. FORMAT: start with "Dear Hiring Team,", then exactly 3 short paragraphs (total 150-220 words), then "Sincerely," and the
   candidate's full name from the MASTER CV, each as its own paragraph. No placeholders, no brackets, no address block, no date,
   no subject line, no headings, no lists, no code fences.
6. Language: English, formal and confident but plain.
7. Mention that the candidate is a Software Engineering student at Sam Houston State University only if it fits; do not
   invent graduation dates or availability.

[MASTER CV]:
{master_raw}

[JOB POSTING]:
{job_description[:6000]}"""
    full, problems = generate_validated(prompt, lambda md: md, lambda md: validate_cl(md, master, master_raw, (employer, job_title, " ".join(re.findall(r"\b[A-Z][a-z]{2,}\b", job_description)))))
    with open("cover_letter.md", "w", encoding="utf-8") as f:
        f.write(full)
    render_pdf(context, full, "cover_letter.pdf", CL_CSS, {"top": "2cm", "right": "2cm", "bottom": "2cm", "left": "2cm"})
    return problems


# --- HANDSHAKE YARDIMCILARI (kayıtlı HTML'e göre) ---
CARD = "[data-hook^='job-result-card |']"
MODAL = "[data-hook='apply-modal-content']"


def safe_goto(page, url, tries=3):
    """Başka bir yönlendirme ile çakışırsa bekleyip tekrar dener."""
    for i in range(tries):
        try:
            page.goto(url)
            return
        except Exception as e:
            if "interrupted by another navigation" in str(e) and i < tries - 1:
                logging.warning(f"Yönlendirme çakıştı, tekrar deneniyor ({i + 1}/{tries - 1})...")
                page.wait_for_timeout(3000)
                continue
            raise


def settle(page, ms=1500):
    try:
        page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    page.wait_for_timeout(ms)


def dump_html(locator, name):
    """Bir elemanın HTML'ini debug/ içine yazar (bir sonraki düzeltme için işe yarar)."""
    try:
        path = f"{DEBUG_DIR}/{name}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(locator.first.evaluate("el => el.outerHTML"))
        logging.info(f"   (HTML kaydedildi: {path})")
    except Exception as e:
        logging.warning(f"HTML kaydedilemedi: {e}")


def collect_job_ids(page):
    page.wait_for_selector(CARD, timeout=20000)
    hooks = page.locator(CARD).evaluate_all("els => els.map(e => e.getAttribute('data-hook'))")
    ids = []
    for h in hooks:
        m = re.search(r"\|\s*(\d+)", h or "")
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def open_job(page, jid):
    safe_goto(page, f"{BASE}/job-search/{jid}?page=1&per_page=25")
    settle(page)
    try:
        page.wait_for_selector(f"a[href*='/jobs/{jid}'] h1", timeout=15000)
    except Exception:
        logging.warning("  Detay paneli başlığı zamanında yüklenmedi.")
    page.wait_for_timeout(1000)


def apply_button_labels(page):
    """Sayfadaki görünür 'apply' içeren butonların adlarını döndürür (loglamak için)."""
    btns = page.get_by_role("button", name=re.compile(r"apply|applied", re.I))
    out = []
    for i in range(btns.count()):
        b = btns.nth(i)
        if b.is_visible():
            out.append((b.get_attribute("aria-label") or b.inner_text()).strip())
    return out


def get_job_info(page, jid):
    t = page.locator(f"a[href*='/jobs/{jid}'] h1")
    title = t.first.inner_text().strip() if t.count() > 0 else f"job-{jid}"
    # 'More' butonuyla açıklamayı genişlet
    more = page.locator("button[aria-label^='Show more']")
    if more.count() > 0:
        try:
            more.first.click()
            page.wait_for_timeout(800)
        except Exception:
            pass
    desc_h = page.locator("h3:has-text('Job description')")
    if desc_h.count() > 0:
        text = desc_h.first.locator("xpath=../..").inner_text().strip()
        logging.info(f"İlan açıklaması 'Job description' bölümünden alındı ({len(text)} karakter).")
    else:
        text = page.locator("main").first.inner_text() if page.locator("main").count() else page.locator("body").inner_text()
        logging.warning("'Job description' bölümü bulunamadı, genel metin kullanıldı.")
    wa = page.locator("[data-hook='work-auth-title']")
    if wa.count() > 0:
        logging.info(f"ℹ️ Çalışma izni notu: {wa.first.inner_text().strip()}")
    emp = page.locator("a[href*='/e/'][aria-label]")
    employer = (emp.first.get_attribute("aria-label") or "").strip() if emp.count() > 0 else ""
    logging.info(f"İşveren: {employer!r}")
    return title, text, employer


def find_fieldset(content, keyword):
    fs = content.locator("fieldset")
    for i in range(fs.count()):
        if keyword in fs.nth(i).inner_text().lower():
            return fs.nth(i)
    return None


BUSY_RE = re.compile(r"converting|uploading|processing|scanning|loading", re.I)


def wait_doc_ready(page, fs, label, timeout_s=45):
    """Belge yüklenip dönüştürme ('Converting...') bitene kadar bekler."""
    stable = 0
    for i in range(timeout_s):
        try:
            txt = fs.inner_text()
            busy = BUSY_RE.search(txt) is not None
            has_file = ".pdf" in txt.lower()
            preview = fs.get_by_text(re.compile(r"preview document", re.I)).count() > 0
            if has_file and not busy:
                stable += 1
                if preview or stable >= 3:
                    logging.info(f"   ✔ {label} hazır ({i + 1} sn).")
                    return True
            else:
                stable = 0
        except Exception:
            stable = 0
        page.wait_for_timeout(1000)
    logging.warning(f"   ⚠️ {label} {timeout_s} sn içinde hazır olmadı.")
    return False


def wait_submit_ready(page, content, timeout_s=20):
    """Pencerede yükleme/dönüştürme bitene ve Submit butonu aktif olana kadar bekler."""
    submit = content.get_by_role("button", name=re.compile(r"submit application", re.I))
    for _ in range(timeout_s):
        try:
            busy = BUSY_RE.search(content.inner_text()) is not None
            if not busy and submit.count() > 0 and submit.first.is_enabled():
                return True
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def replace_doc(page, content, keyword, path, label):
    """Fieldset'teki ekli belgeyi kaldırıp kendi PDF'imizi yükler."""
    fs = find_fieldset(content, keyword)
    if fs is None:
        logging.warning(f"⚠️ '{keyword}' bölümü pencerede yok, {label} yüklenmedi.")
        return False
    logging.info(f"📤 {label} bölümü: {fs.inner_text().strip()[:150]!r}")
    dump_html(fs, f"fieldset_{keyword.replace(' ', '_')}_once")

    # Ekli belge varsa kaldır (Close butonu)
    close = fs.locator("button[aria-label='Close']")
    if close.count() > 0 and fs.locator("input[type='file']").count() == 0:
        logging.info("   Ekli belge kaldırılıyor (Close)...")
        close.first.click()
        page.wait_for_timeout(1200)
        step(page, f"{label} kaldirildi")
        dump_html(fs, f"fieldset_{keyword.replace(' ', '_')}_sonra")

    inp = fs.locator("input[type='file']")
    try:
        if inp.count() > 0:
            inp.first.set_input_files(path)
        else:
            with page.expect_file_chooser(timeout=6000) as fc:
                fs.get_by_text(re.compile(r"upload|browse|choose|select|drag|attach", re.I)).first.click()
            fc.value.set_files(path)
        page.wait_for_timeout(1000)
        wait_doc_ready(page, fs, label)
        logging.info(f"✅ {label} yüklendi: {fs.inner_text().strip()[:150]!r}")
        step(page, f"{label} yuklendi")
        return True
    except Exception as e:
        logging.warning(f"⚠️ {label} yüklenemedi: {e}")
        step(page, f"{label} yukleme hatasi")
        return False


# --- ANA AKIŞ ---
def recover(page):
    """Hata sonrası açık kalan pencereyi kapatıp sayfayı temiz duruma getirir."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        close_btn = page.locator("button[aria-label='Close']")
        if close_btn.count() > 0 and close_btn.first.is_visible():
            close_btn.first.click(timeout=3000)
            page.wait_for_timeout(500)
        # "Discard / Leave" gibi onay çıkarsa geç
        for name in ("discard", "leave", "yes"):
            b = page.get_by_role("button", name=re.compile(name, re.I))
            if b.count() > 0 and b.first.is_visible():
                b.first.click(timeout=2000)
                break
    except Exception:
        pass


def withdraw_visible(page):
    """Başvuru gerçekten kaydedildiyse ilan sayfasında 'Withdraw application' butonu çıkar."""
    try:
        w = page.get_by_role("button", name=re.compile(r"withdraw application", re.I))
        return w.count() > 0 and w.first.is_visible()
    except Exception:
        return False


def wait_for_applied(page, timeout_s):
    """'Withdraw application' butonu görünene kadar en fazla timeout_s saniye bekler."""
    for i in range(timeout_s):
        if withdraw_visible(page):
            logging.info(f"  ✔ 'Withdraw application' göründü ({i} sn).")
            return True
        page.wait_for_timeout(1000)
    return withdraw_visible(page)


def confirm_applied(page, jid):
    """Başvurunun gerçekten tamamlandığını doğrular. 30 sn içinde çıkmazsa sayfayı yenileyip son kez bakar."""
    logging.info(f"  ⏳ Başvurunun kaydedilmesi bekleniyor (en fazla {APPLY_CONFIRM_TIMEOUT} sn)...")
    if wait_for_applied(page, APPLY_CONFIRM_TIMEOUT):
        return True
    # Pencerede hata/uyarı var mı, logla (eksik zorunlu alan vb.)
    try:
        modal = page.locator(MODAL)
        if modal.count() > 0 and modal.first.is_visible():
            logging.warning(f"  Pencere hâlâ açık: {modal.first.inner_text().strip()[-300:]!r}")
            dump_html(modal, f"modal_basarisiz_{jid}")
    except Exception:
        pass
    step(page, f"onay gelmedi {jid}")
    logging.warning("  ⚠️ Onay gelmedi, sayfa yenilenip son kez kontrol ediliyor...")
    try:
        open_job(page, jid)
    except Exception as e:
        logging.warning(f"  Sayfa yenilenemedi: {str(e).splitlines()[0][:100]}")
    return wait_for_applied(page, 8)


def process_job(page, context, jid):
    """Döndürür: 'applied' (doğrulanmış başvuru), 'skipped' veya 'failed'."""
    logging.info(f"\n[İLAN İNCELENİYOR]: {BASE}/job-search/{jid}")
    open_job(page, jid)
    labels = apply_button_labels(page)

    if (any(re.match(r"applied", l, re.I) for l in labels)
            or withdraw_visible(page)
            or page.get_by_text(re.compile(r"^Applied on ", re.I)).count() > 0):
        logging.info("  → Daha önce başvurulmuş. Atlanıyor.")
        return "skipped"

    apply_btn = page.locator("button[aria-label='Quick apply'], button[aria-label='Apply']")
    if apply_btn.count() == 0:
        logging.info("  → Uygun başvuru butonu yok. Atlanıyor.")
        return "skipped"

    logging.info("  → Başvuru butonu bulundu ✅")

    title, job_text, employer = get_job_info(page, jid)
    is_sw = is_software_job(title, job_text)
    if not is_sw:
        logging.info("  → Başlık/açıklama filtresi: uygun değil. Atlanıyor.")
        return "skipped"

    # 4) QUICK APPLY PENCERESİ
    if not apply_btn.first.is_enabled():
        logging.info("  → Başvuru butonu pasif (disabled). Atlanıyor.")
        return "skipped"

    apply_btn.first.click(timeout=10000)
    content = page.locator(MODAL).first
    content.wait_for(state="visible", timeout=15000)
    page.wait_for_timeout(1000)

    modal_text = content.inner_text()
    needs_resume = find_fieldset(content, "resume") is not None
    cl_fs = find_fieldset(content, "cover letter")

    # 5) BELGELERİ ÜRET VE YÜKLE
    if needs_resume:
        generate_cv_pdf(title, job_text, context, is_sw)
        replace_doc(page, content, "resume", "cv.pdf", "Resume")

    # Cover letter her zaman hazırla, opsiyonel de olsa yükle
    generate_cover_letter_pdf(title, job_text, context, employer)
    if cl_fs is not None:
        replace_doc(page, content, "cover letter", "cover_letter.pdf", "Cover Letter")
    else:
        logging.info("  ℹ️ Cover letter alanı yok, hazırlanan belge kullanılmadı.")

    # Ek bölümleri (soruları) kontrol et ama onay beklemeden atla
    others = []
    fs_all = content.locator("fieldset")
    for i in range(fs_all.count()):
        t = fs_all.nth(i).inner_text().lower()
        if "resume" not in t and "cover letter" not in t:
            others.append(fs_all.nth(i).inner_text().strip()[:80])
    if others:
        logging.warning(f"⚠️ Tanınmayan alanlar/sorular var: {others}. Başvuru başarısız olabilir ancak deneniyor...")

    # 6) GÖNDER
    submit = content.get_by_role("button", name=re.compile(r"submit application", re.I))
    if submit.count() == 0:
        logging.error("❌ 'Submit Application' butonu bulunamadı, diğer ilana geçiliyor.")
        return "failed"

    # Yüklemeler/dönüştürme bitmeden Submit'e basma (aksi halde başvuru takılıyor)
    for kw, lb in (("resume", "Resume"), ("cover letter", "Cover Letter")):
        fs = find_fieldset(content, kw)
        if fs is not None and ".pdf" in fs.inner_text().lower():
            wait_doc_ready(page, fs, lb)
    if not wait_submit_ready(page, content):
        logging.warning("  ⚠️ Submit butonu hazır görünmüyor, yine de deneniyor...")
    page.wait_for_timeout(1500)

    step(page, f"submit oncesi {jid}")
    submit.first.click(timeout=15000)   # buton pasifse (yükleme sürüyorsa) aktif olana kadar bekler
    logging.info("  📨 Submit Application tıklandı.")

    # 7) 'Withdraw application' çıkana kadar bekle (en fazla 30 sn). Çıkmadan pencereyi kapatma!
    if not confirm_applied(page, jid):
        logging.error("❌ Başvuru doğrulanamadı ('Withdraw application' yok). Başvuru yapılmamış sayılıyor.")
        recover(page)
        return "failed"

    logging.info("🎉 Başvuru doğrulandı (Withdraw application görünüyor).")
    step(page, f"basvuru dogrulandi {jid}")

    # Pencere hâlâ açıksa kapat, sonra sıradaki ilana geç
    try:
        close_btn = page.locator("[data-hook='apply-modal-close-button']")
        if close_btn.count() > 0 and close_btn.first.is_visible():
            close_btn.first.click(timeout=3000)
            settle(page, 1000)
    except Exception:
        pass
    return "applied"


def handshake_bot():
    print("\n--- Handshake Akıllı Başvuru Botu (TAM OTOMATİK MOD) ---")
    if not os.path.exists("master_cv.json"):
        logging.error("master_cv.json bulunamadı!")
        return
    for f in ("cv.pdf", "cover_letter.pdf"):
        if os.path.exists(f):
            os.remove(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # 1) MANUEL GİRİŞ (Baştaki güvenlik duvarını geçmek için bir kez gereklidir)
        page.goto(LOGIN_URL)
        step(page, "login sayfasi")
        input(">> Tarayıcıda giriş yap. Giriş bitip ana sayfa yüklenince buraya dönüp ENTER'a bas... ")

        # 2) SAYFALARI DÖNGÜYE AL
        sayfa_no = 1
        sayfa_hata = 0
        stats = {"applied": 0, "skipped": 0, "failed": 0}
        while True:
            # Doğrudan ilgili sayfa numarasına gidiyoruz[cite: 1]
            search_page_url = f"{BASE}/job-search/{SEARCH_ID}?page={sayfa_no}&per_page=25"
            logging.info(f"\n--- SAYFA {sayfa_no} TARANIYOR ---")
            
            try:
                safe_goto(page, search_page_url)
                settle(page, 4000)
                step(page, f"ilan_listesi_sayfa_{sayfa_no}")
                ids = collect_job_ids(page)
                sayfa_hata = 0
            except Exception as e:
                sayfa_hata += 1
                logging.error(f"❌ Sayfa {sayfa_no} yüklenemedi ({sayfa_hata}/3): {str(e).splitlines()[0][:150]}")
                if sayfa_hata >= 3:
                    logging.info("  → 3 denemede olmadı, sonraki sayfaya geçiliyor.")
                    sayfa_no += 1
                    sayfa_hata = 0
                continue
            if not ids:
                logging.info("Bu sayfada ilan bulunamadı veya ilanlar bitti. Tarama tamamlandı.")
                break
                
            logging.info(f"Sayfa {sayfa_no} üzerinde {len(ids)} ilan bulundu.")

            # 3) SAYFADAKİ İLANLARI TEK TEK DOLAŞ
            for jid in ids:
                try:
                    stats[process_job(page, context, jid) or "skipped"] += 1
                except Exception as e:
                    stats["failed"] += 1
                    logging.error(f"❌ İlan {jid} işlenirken hata: {type(e).__name__}: {str(e).splitlines()[0][:150]}")
                    logging.info("  → Hata atlandı, sonraki ilana geçiliyor.")
                    recover(page)
                    continue

            # For döngüsü bitti (sayfadaki tüm ilanlara bakıldı), sonraki sayfaya geç[cite: 1]
            sayfa_no += 1

        logging.info(f"\n📊 ÖZET → başvurulan (doğrulanmış): {stats['applied']} | atlanan: {stats['skipped']} | başarısız: {stats['failed']}")


if __name__ == "__main__":
    handshake_bot()
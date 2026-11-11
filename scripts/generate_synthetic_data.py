"""
Generate SYNTHETIC (fictional) rice market data and documents for RiceRate AI Pakistan.

Every number produced here is FICTIONAL DEMONSTRATION DATA. It is generated from a
seeded random model so that all CSV, Excel, TXT and PDF files are numerically
consistent with each other (the PDF reports quote the same prices as the CSVs).

Usage (from the project root):
    python scripts/generate_synthetic_data.py
"""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYN_DIR = ROOT / "data" / "synthetic"
DOC_DIR = ROOT / "data" / "documents"
SAMPLE_DIR = ROOT / "data" / "samples"

SEED = 1121
END_DATE = date(2026, 11, 10)  # last synthetic observation date (fixed, reproducible)
DAYS = 45
LABEL = "SYNTHETIC DEMONSTRATION DATA - FICTIONAL PRICES, NOT REAL MARKET QUOTATIONS"
SOURCE_NAME = "RiceRate Synthetic Demo Generator"

LOWER_PUNJAB = ["Multan", "Muzaffargarh", "Bahawalpur", "Rahim Yar Khan"]
CITY_OFFSET = {"Multan": 0.0, "Muzaffargarh": -0.010, "Bahawalpur": -0.005, "Rahim Yar Khan": -0.015}


@dataclass(frozen=True)
class Product:
    key: str
    name: str
    product_type: str  # paddy | rice | broken_rice
    variety: str
    grade: str
    punjab_base: float  # PKR per 40 kg (Lower Punjab mandi / mill-gate wholesale)
    karachi_base: float | None  # PKR per kg (Karachi wholesale); None = not traded in Karachi data
    trend: str  # basmati_up | irri_soft | stable


PRODUCTS = [
    Product("paddy_1121_basmati", "1121 Basmati Paddy", "paddy", "1121 Basmati", "Standard (moisture <=16%)", 4600, None, "basmati_up"),
    Product("paddy_super_basmati", "Super Basmati Paddy", "paddy", "Super Basmati", "Standard (moisture <=16%)", 4100, None, "basmati_up"),
    Product("paddy_irri6", "IRRI-6 Paddy", "paddy", "IRRI-6", "Standard (moisture <=16%)", 2600, None, "irri_soft"),
    Product("paddy_pk386", "PK-386 Paddy", "paddy", "PK-386", "Standard (moisture <=16%)", 3300, None, "stable"),
    Product("rice_1121_sella", "1121 Basmati Sella Rice", "rice", "1121 Basmati", "Sella - Premium", 11800, 305, "basmati_up"),
    Product("rice_1121_steam", "1121 Basmati Steam Rice", "rice", "1121 Basmati", "Steam - Premium", 12400, 320, "basmati_up"),
    Product("rice_super_basmati", "Super Basmati Rice", "rice", "Super Basmati", "Kernel - Premium", 11000, 285, "basmati_up"),
    Product("rice_irri6_15", "IRRI-6 White Rice", "rice", "IRRI-6", "15% Broken", 5600, 148, "irri_soft"),
    Product("broken_1121_b1", "1121 Broken Rice (B1)", "broken_rice", "1121 Basmati", "B1 Broken", 7200, 188, "stable"),
    Product("broken_irri6_100", "IRRI-6 Broken Rice", "broken_rice", "IRRI-6", "100% Broken", 4000, 106, "stable"),
]


@dataclass(frozen=True)
class IntlSeries:
    key: str
    name: str
    variety: str
    grade: str
    country: str
    market: str
    start: float
    end: float


INTL = [
    IntlSeries("export_pk_1121_sella", "Pakistan 1121 Basmati Sella (export)", "1121 Basmati", "Sella 2% Broken", "Pakistan", "FOB Karachi", 1050, 1080),
    IntlSeries("export_pk_irri6_5", "Pakistan IRRI-6 White 5% (export)", "IRRI-6", "5% Broken", "Pakistan", "FOB Karachi", 380, 376),
    IntlSeries("export_in_1121", "India 1121 Basmati Sella (export)", "1121 Basmati", "Sella 2% Broken", "India", "FOB Kandla", 1020, 1030),
    IntlSeries("export_in_parboiled_5", "India Parboiled 5% (export)", "Non-Basmati Parboiled", "5% Broken", "India", "FOB Kakinada", 375, 366),
    IntlSeries("export_th_white_5", "Thailand White 5% (export)", "Thai White", "5% Broken", "Thailand", "FOB Bangkok", 420, 402),
    IntlSeries("export_vn_white_5", "Vietnam White 5% (export)", "Vietnam White", "5% Broken", "Vietnam", "FOB Ho Chi Minh City", 395, 383),
]


def trend_factor(trend: str, t: int) -> float:
    """Multiplicative trend at day t (0..DAYS-1). Last 14 days carry the 'story'."""
    rise_start = DAYS - 14
    if t < rise_start:
        return 1.0
    frac = (t - rise_start) / 13
    return {"basmati_up": 1 + 0.040 * frac, "irri_soft": 1 - 0.015 * frac}.get(trend, 1.0)


def dates() -> list[date]:
    return [END_DATE - timedelta(days=DAYS - 1 - i) for i in range(DAYS)]


def r10(x: float) -> float:
    return float(int(round(x / 10.0)) * 10)


def generate_prices(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    ds = dates()
    for p in PRODUCTS:
        for city in LOWER_PUNJAB + ["Karachi"]:
            if city == "Karachi" and p.karachi_base is None:
                continue
            noise = 0.0
            for t, d in enumerate(ds):
                # realistic gaps: some markets do not publish every day (never skip the last day for Multan/Karachi)
                if t < DAYS - 1 and rng.random() < 0.07:
                    continue
                if t == DAYS - 1 and city in ("Rahim Yar Khan",) and p.product_type == "paddy":
                    continue  # RYK paddy not reported on the last day -> demonstrates stale data handling
                noise = 0.6 * noise + rng.gauss(0, 0.004)
                f = trend_factor(p.trend, t) * (1 + noise)
                if city == "Karachi":
                    price = round(p.karachi_base * f * (1 + 0.004 * (t >= DAYS - 14)), 0)
                    unit, category, market = "PKR/kg", "wholesale", "Karachi Wholesale Grain Market"
                else:
                    price = r10(p.punjab_base * f * (1 + CITY_OFFSET[city]))
                    unit = "PKR/40kg"
                    category = "wholesale"
                    market = f"{city} Grain Market" if p.product_type == "paddy" else f"{city} Mill-Gate"
                hour = 10 if city != "Karachi" else 13
                rows.append({
                    "product_key": p.key, "product_name": p.name, "product_type": p.product_type,
                    "variety": p.variety, "grade": p.grade, "market": market, "city": city,
                    "province": "Sindh" if city == "Karachi" else "Punjab", "country": "Pakistan",
                    "price": price, "currency": "PKR", "unit": unit, "price_category": category,
                    "observed_at": datetime(d.year, d.month, d.day, hour, 0).isoformat(),
                    "source_name": SOURCE_NAME,
                    "source_document": "Historical_Rice_Prices.csv",
                    "data_label": "SYNTHETIC",
                })
    # international weekly export quotations (Thursdays)
    thursdays = [d for d in ds if d.weekday() == 3]
    for s in INTL:
        n = len(thursdays)
        for i, d in enumerate(thursdays):
            base = s.start + (s.end - s.start) * (i / max(n - 1, 1))
            price = float(int(round(base * (1 + rng.gauss(0, 0.003)) / 5.0)) * 5)
            if i == n - 1:
                price = s.end
            rows.append({
                "product_key": s.key, "product_name": s.name,
                "product_type": "broken_rice" if "100%" in s.grade else "rice",
                "variety": s.variety, "grade": s.grade, "market": s.market,
                "city": s.market.replace("FOB ", ""), "province": "", "country": s.country,
                "price": price, "currency": "USD", "unit": "USD/MT", "price_category": "export",
                "observed_at": datetime(d.year, d.month, d.day, 16, 0).isoformat(),
                "source_name": SOURCE_NAME, "source_document": "International_Rice_Price_Report.pdf",
                "data_label": "SYNTHETIC",
            })
    return rows


def generate_quotations(rng: random.Random, prices: list[dict]) -> list[dict]:
    buyers = ["Demo Buyer A (Fictional Exports Ltd)", "Demo Buyer B (Fictional Traders)",
              "Demo Buyer C (Fictional Rice House)", "Demo Buyer D (Fictional Commodities)"]
    karachi = [p for p in prices if p["city"] == "Karachi"]
    latest: dict[str, dict] = {}
    for p in karachi:
        latest[p["product_key"]] = p  # rows are in date order -> last wins
    rows = []
    qid = 1
    for offset in range(9, -1, -1):
        d = END_DATE - timedelta(days=offset)
        for key in ["rice_1121_sella", "rice_super_basmati", "broken_1121_b1", "broken_irri6_100", "rice_irri6_15"]:
            if rng.random() < 0.45:
                continue
            ref = latest[key]
            price = round(ref["price"] * (1 + rng.uniform(-0.012, 0.012)) * (1 - 0.0015 * offset), 0)
            rows.append({
                "quotation_id": f"SYN-KQ-{qid:03d}", "buyer": rng.choice(buyers),
                "product_key": key, "product_name": ref["product_name"], "variety": ref["variety"],
                "grade": ref["grade"], "city": "Karachi", "price": price, "currency": "PKR",
                "unit": "PKR/kg", "quantity_mt": rng.choice([25, 50, 100, 200]),
                "delivery_terms": rng.choice(["Ex-warehouse Karachi", "Delivered Karachi Port", "Ex-mill, buyer transport"]),
                "quoted_at": datetime(d.year, d.month, d.day, rng.choice([11, 12, 15, 17]), 0).isoformat(),
                "valid_until": (d + timedelta(days=rng.choice([2, 3, 5]))).isoformat(),
                "source_document": "Karachi_Buyer_Quotations.csv", "data_label": "SYNTHETIC",
            })
            qid += 1
    return rows


NEWS = [
    # (days_before_end, region, category, title, summary)
    (0, "Lower Punjab", "news", "Basmati paddy arrivals slow in Lower Punjab mandis",
     "Fictional report: arrivals of new-crop 1121 and Super Basmati paddy at Multan, Muzaffargarh and Bahawalpur grain markets were described as slower than the previous week because many growers held stocks expecting better rates. Brokers said this supported paddy prices over the last two weeks."),
    (1, "Karachi", "news", "Karachi exporters book steady 1121 Sella volumes",
     "Fictional report: Karachi wholesale traders reported steady buying of 1121 Basmati Sella for Middle East destinations. Higher paddy costs in Punjab were cited as the main reason Karachi Sella quotations moved up."),
    (2, "International", "commentary", "Thai and Vietnamese 5% broken quotes ease on ample supply",
     "Fictional commentary: export quotations for Thai and Vietnamese 5% broken white rice drifted lower over recent weeks as harvest supplies built up and buyer demand from Asian importers stayed cautious."),
    (3, "International", "news", "India non-basmati export offers remain competitive",
     "Fictional report: Indian parboiled 5% export offers were reported slightly lower, keeping competition intense for Pakistani IRRI-6 exporters in African markets."),
    (4, "Pakistan", "news", "Freight costs to Gulf stable this week",
     "Fictional report: container freight from Karachi to Gulf ports was described as broadly stable, giving no major new pressure on export parity prices this week."),
    (5, "Lower Punjab", "news", "IRRI-6 paddy prices soften in Rahim Yar Khan",
     "Fictional report: IRRI-6 paddy demand from mills in Rahim Yar Khan and Bahawalpur was described as subdued, with millers citing weaker export enquiries for coarse rice."),
    (6, "Karachi", "news", "Broken rice demand from feed and food processors steady",
     "Fictional report: demand for 1121 B1 broken and IRRI-6 100% broken rice in Karachi remained steady; traders reported no major change in quoted rates."),
    (8, "International", "commentary", "Global rice market: importers wait for clearer price signals",
     "Fictional commentary: major importers in Asia and Africa were said to be buying hand-to-mouth, waiting for clearer signals on Asian harvest volumes. Analysts in this synthetic report did not expect sharp moves in the short term but noted uncertainty."),
    (10, "Pakistan", "news", "Pakistan basmati exporters report stronger enquiries",
     "Fictional report: Pakistani basmati exporters said enquiries from Gulf and European buyers improved, which supported domestic Basmati paddy and Sella rice prices."),
    (12, "Lower Punjab", "news", "Moisture complaints reported in early paddy lots",
     "Fictional report: some early Basmati paddy lots arriving in Muzaffargarh carried higher moisture, leading to quality deductions by mills. Dry, standard-quality lots received full rates."),
    (16, "International", "news", "Vietnam harvest progress adds to export availability",
     "Fictional report: harvest progress in the Mekong Delta increased exportable supplies of Vietnamese white rice, a factor in slightly lower FOB offers."),
    (20, "Pakistan", "commentary", "Monthly view: Pakistan rice prices broadly stable",
     "Fictional commentary: during the earlier part of the review period Pakistan rice prices were broadly stable, with only small day-to-day changes in Lower Punjab mandis and Karachi wholesale markets."),
]


def generate_news() -> list[dict]:
    out = []
    for i, (back, region, cat, title, summary) in enumerate(NEWS, 1):
        d = END_DATE - timedelta(days=back)
        out.append({
            "article_id": f"SYN-NEWS-{i:03d}", "title": f"{title} (SYNTHETIC)", "summary": summary,
            "region": region, "category": cat, "published_at": datetime(d.year, d.month, d.day, 18, 0).isoformat(),
            "source_name": "RiceRate Synthetic Newsroom (fictional)", "url": "",
            "source_document": "Pakistan_Rice_Export_News.pdf" if region in ("Pakistan", "Karachi", "Lower Punjab") else "Global_Rice_Market_Commentary.txt",
            "data_label": "SYNTHETIC",
        })
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- analytics helpers for documents
def series(prices, key, city):
    return [p for p in prices if p["product_key"] == key and p["city"] == city]


def latest_and_change(prices, key, city, days):
    s = series(prices, key, city)
    if not s:
        return None
    last = s[-1]
    last_d = datetime.fromisoformat(last["observed_at"]).date()
    base = [p for p in s if datetime.fromisoformat(p["observed_at"]).date() <= last_d - timedelta(days=days)]
    if not base:
        return last, None, None
    b = base[-1]
    return last, last["price"] - b["price"], (last["price"] - b["price"]) / b["price"] * 100


def fmt(x: float, unit: str) -> str:
    return f"{x:,.0f} {unit}"


# ---------------------------------------------------------------- PDF writing
def build_pdf(path: Path, title: str, pub: date, paragraphs: list[str], tables: list[tuple[str, list[list[str]]]]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title=title, author=SOURCE_NAME)
    story = [Paragraph(f"<font color='#B00020'><b>{LABEL}</b></font>", styles["Normal"]), Spacer(1, 6),
             Paragraph(title, styles["Title"]),
             Paragraph(f"Publication date: {pub.isoformat()} | Publisher: {SOURCE_NAME} (fictional)", styles["Normal"]),
             Spacer(1, 10)]
    for para in paragraphs:
        story += [Paragraph(para, styles["BodyText"]), Spacer(1, 6)]
    for caption, rows in tables:
        story += [Spacer(1, 6), Paragraph(f"<b>{caption}</b>", styles["Heading4"])]
        t = Table(rows, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B2545")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF4F0")]),
        ]))
        story.append(t)
    story += [Spacer(1, 12), Paragraph(f"<i>{LABEL}. Generated for an educational RAG homework project.</i>", styles["Normal"])]
    doc.build(story)


def direction(pct):
    if pct is None:
        return "insufficient data"
    return "rising" if pct > 1.5 else "falling" if pct < -1.5 else "stable"


def build_documents(prices, quotes, news) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    end = END_DATE

    # 1. Lower Punjab daily paddy prices
    rows = [["City", "Product", "Latest price", "Obs. date", "7-day change", "Direction"]]
    for city in LOWER_PUNJAB:
        for p in [x for x in PRODUCTS if x.product_type == "paddy"]:
            r = latest_and_change(prices, p.key, city, 7)
            last, chg, pct = r
            rows.append([city, p.name, fmt(last["price"], "PKR/40kg"), last["observed_at"][:10],
                         "n/a" if chg is None else f"{chg:+,.0f} ({pct:+.1f}%)", direction(pct)])
    m = latest_and_change(prices, "paddy_1121_basmati", "Multan", 7)
    build_pdf(DOC_DIR / "Lower_Punjab_Daily_Paddy_Prices.pdf", "Lower Punjab Daily Paddy Price Report", end, [
        f"This fictional daily report covers paddy (dhaan) prices at four Lower Punjab grain markets: Multan, Muzaffargarh, Bahawalpur and Rahim Yar Khan. All prices are wholesale mandi prices in PKR per 40 kg (one maund) for standard quality paddy with moisture up to 16%.",
        f"In Multan, 1121 Basmati paddy was quoted at {fmt(m[0]['price'], 'PKR/40kg')} on {m[0]['observed_at'][:10]}, a change of {m[1]:+,.0f} PKR ({m[2]:+.1f}%) over seven days. Basmati paddy prices (1121 and Super Basmati) rose during the last two weeks because arrivals slowed as growers held stocks and exporters reported stronger enquiries.",
        "IRRI-6 paddy prices were slightly softer because mills reported weaker export demand for coarse rice. PK-386 paddy was broadly stable.",
        "Rahim Yar Khan did not report paddy prices on the latest day; the table shows the last available observation with its original date. Readers should not treat an older observation as today's rate.",
    ], [("Lower Punjab paddy prices (PKR per 40 kg)", rows)])

    # 2. Karachi rice market report
    rows = [["Product", "Grade", "Latest price", "Obs. date", "7-day change", "Direction"]]
    for p in [x for x in PRODUCTS if x.karachi_base]:
        last, chg, pct = latest_and_change(prices, p.key, "Karachi", 7)
        rows.append([p.name, p.grade, fmt(last["price"], "PKR/kg"), last["observed_at"][:10],
                     "n/a" if chg is None else f"{chg:+,.0f} ({pct:+.1f}%)", direction(pct)])
    k = latest_and_change(prices, "rice_1121_sella", "Karachi", 7)
    build_pdf(DOC_DIR / "Karachi_Rice_Market_Report.pdf", "Karachi Rice Market Report", end, [
        "This fictional report summarises wholesale rice prices in the Karachi wholesale grain market. Prices are in PKR per kg for finished (milled) rice and broken rice.",
        f"1121 Basmati Sella was quoted at {fmt(k[0]['price'], 'PKR/kg')} on {k[0]['observed_at'][:10]} ({k[2]:+.1f}% over seven days). Traders linked the increase to higher Basmati paddy costs in Punjab and steady export bookings to Gulf buyers.",
        "Karachi prices normally include transport from Punjab mills, handling and trader margin, so Karachi rates are usually above Lower Punjab mill-gate rates for the same variety and grade.",
        "IRRI-6 white rice was slightly weaker due to competition from Indian non-basmati export offers. Broken rice prices were stable.",
    ], [("Karachi wholesale rice prices (PKR per kg)", rows)])

    # 3. International rice price report
    rows = [["Origin", "Product", "Grade", "Market", "Latest (USD/MT)", "Date"]]
    for s in INTL:
        last = series(prices, s.key, s.market.replace("FOB ", ""))[-1]
        rows.append([s.country, s.name, s.grade, s.market, f"{last['price']:,.0f}", last["observed_at"][:10]])
    build_pdf(DOC_DIR / "International_Rice_Price_Report.pdf", "International Rice Export Price Report", end, [
        "This fictional weekly report lists export (FOB) quotations in US dollars per metric ton for Pakistan, India, Thailand and Vietnam. Export FOB quotations are NOT the same as Pakistani domestic wholesale prices: they include milling to export specification, bagging, inland freight and exporter margin, and are priced in USD.",
        f"Thai white 5% broken eased from about {INTL[4].start:.0f} to {INTL[4].end:.0f} USD/MT and Vietnamese white 5% from about {INTL[5].start:.0f} to {INTL[5].end:.0f} USD/MT over the review period because of ample harvest supplies. Indian parboiled 5% offers also softened.",
        f"In contrast, basmati export quotations were firm: Pakistan 1121 Sella moved from about {INTL[0].start:.0f} to {INTL[0].end:.0f} USD/MT on stronger Gulf demand.",
        "Interpretation (not a forecast): softer non-basmati export offers may limit upside for coarse rice such as IRRI-6, while basmati remains supported by demand. Future price direction is uncertain.",
    ], [("Latest export quotations (USD per metric ton, FOB)", rows)])

    # 4. Weekly rice price analysis
    rows = [["Product", "City", "Latest", "7-day %", "15-day %", "30-day %"]]
    for key, city, unit in [("paddy_1121_basmati", "Multan", "PKR/40kg"), ("paddy_irri6", "Bahawalpur", "PKR/40kg"),
                            ("rice_1121_sella", "Multan", "PKR/40kg"), ("rice_1121_sella", "Karachi", "PKR/kg"),
                            ("rice_irri6_15", "Karachi", "PKR/kg"), ("broken_irri6_100", "Karachi", "PKR/kg")]:
        name = next(p.name for p in PRODUCTS if p.key == key)
        r7, r15, r30 = (latest_and_change(prices, key, city, n) for n in (7, 15, 30))
        f = lambda r: "n/a" if r[2] is None else f"{r[2]:+.1f}%"
        rows.append([name, city, fmt(r7[0]["price"], unit), f(r7), f(r15), f(r30)])
    build_pdf(DOC_DIR / "Weekly_Rice_Price_Analysis.pdf", "Weekly Rice Price Analysis", end, [
        "This fictional weekly analysis compares 7-day, 15-day and 30-day percentage changes for key rice products. A change above +1.5% is labelled rising, below -1.5% falling, and in between stable.",
        "Main observation: Basmati products (1121 and Super Basmati paddy and rice) rose by roughly three to four percent over the last two weeks after a broadly stable first month. Coarse IRRI-6 products were slightly lower. Broken rice was stable.",
        "Drivers mentioned in market reports: slower paddy arrivals in Lower Punjab, stronger basmati export enquiries, and softer international prices for non-basmati rice from Thailand, Vietnam and India.",
        "Caution: these changes describe the past. They do not guarantee future price direction.",
    ], [("Price changes by product", rows)])

    # 5. Pakistan rice export news
    pk_news = [n for n in news if n["region"] in ("Pakistan", "Karachi", "Lower Punjab")]
    build_pdf(DOC_DIR / "Pakistan_Rice_Export_News.pdf", "Pakistan Rice Market and Export News Digest", end,
              ["This digest collects fictional news items about Pakistan's domestic rice market and rice exports."] +
              [f"<b>{n['published_at'][:10]} - {n['title']}</b>: {n['summary']}" for n in pk_news], [])

    # 6. Broken rice market report
    rows = [["Product", "City", "Latest price", "Obs. date", "7-day change"]]
    for p in [x for x in PRODUCTS if x.product_type == "broken_rice"]:
        for city, unit in [("Multan", "PKR/40kg"), ("Bahawalpur", "PKR/40kg"), ("Karachi", "PKR/kg")]:
            last, chg, pct = latest_and_change(prices, p.key, city, 7)
            rows.append([p.name, city, fmt(last["price"], unit), last["observed_at"][:10],
                         "n/a" if chg is None else f"{chg:+,.0f} ({pct:+.1f}%)"])
    b = latest_and_change(prices, "broken_irri6_100", "Karachi", 7)
    build_pdf(DOC_DIR / "Broken_Rice_Market_Report.pdf", "Broken Rice Market Report", end, [
        "Broken rice (toota chawal) is a by-product of milling. This fictional report covers 1121 B1 broken and IRRI-6 100% broken rice.",
        f"In Karachi, IRRI-6 100% broken was quoted at {fmt(b[0]['price'], 'PKR/kg')} on {b[0]['observed_at'][:10]}. Demand from food processors and feed buyers was steady and prices were broadly stable.",
        "Lower Punjab broken rice prices are quoted per 40 kg at the mill gate; Karachi prices are per kg. Convert units before comparing (1 maund = 40 kg).",
    ], [("Broken rice prices", rows)])

    # 7. Rice variety price guide
    rows = [["Variety", "Product type", "Grade", "Typical unit (Punjab)", "Typical unit (Karachi)"]]
    for p in PRODUCTS:
        rows.append([p.variety, p.product_type, p.grade, "PKR/40kg", "PKR/kg" if p.karachi_base else "-"])
    build_pdf(DOC_DIR / "Rice_Variety_Price_Guide.pdf", "Rice Variety and Price Unit Guide", end, [
        "Paddy (dhaan) is unmilled rice with husk. Finished rice (chawal) is milled rice. Paddy and finished rice prices must never be compared directly.",
        "1121 Basmati is an extra-long grain basmati variety, sold mainly as Sella (parboiled) or Steam rice. Super Basmati is a traditional aromatic basmati. IRRI-6 is a coarse long-grain non-basmati variety widely exported to Africa. PK-386 is a non-basmati long-grain variety.",
        "Common units: PKR per 40 kg (one maund, common in Punjab mandis), PKR per kg (common in Karachi wholesale), PKR per 100 kg, PKR per metric ton, and USD per metric ton for exports. 1 metric ton = 1,000 kg = 25 maunds.",
        "Price categories: wholesale (mandi or mill-gate), retail (consumer shops), export (FOB quotations) and broker quotations (offers from buyers, valid for a limited time).",
    ], [("Varieties and grades in this dataset", rows)])

    # 8. Historical prices CSV (domestic subset)
    hist = [{k: p[k] for k in ("observed_at", "product_name", "variety", "grade", "city", "market", "price",
                               "currency", "unit", "price_category", "data_label")}
            for p in prices if p["country"] == "Pakistan"]
    for h in hist:
        h["observed_at"] = h["observed_at"][:10]
    write_csv(DOC_DIR / "Historical_Rice_Prices.csv", hist)

    # 9. Karachi buyer quotations CSV
    write_csv(DOC_DIR / "Karachi_Buyer_Quotations.csv",
              [{k: q[k] for k in ("quotation_id", "buyer", "product_name", "grade", "price", "currency", "unit",
                                  "quantity_mt", "delivery_terms", "quoted_at", "valid_until", "data_label")} for q in quotes])

    # 10. Global commentary TXT
    intl_news = [n for n in news if n["region"] == "International"]
    txt = [LABEL, "", "GLOBAL RICE MARKET COMMENTARY (FICTIONAL)", f"Publication date: {end.isoformat()}", ""]
    for n in intl_news:
        txt += [f"[{n['published_at'][:10]}] {n['title']}", n["summary"], ""]
    txt += ["Summary interpretation: international non-basmati export prices (Thai, Vietnamese and Indian 5% broken) "
            "showed a mild downward drift during the period, while basmati export prices were firm. These are signals, "
            "not certainties; weather, government export policies, currency movements and freight can change direction quickly.", "", LABEL]
    (DOC_DIR / "Global_Rice_Market_Commentary.txt").write_text("\n".join(txt), encoding="utf-8")

    # 11. Weekly market news TXT
    txt = [LABEL, "", "WEEKLY RICE MARKET NEWS (FICTIONAL)", f"Week ending: {end.isoformat()}", ""]
    for n in [x for x in news if (END_DATE - datetime.fromisoformat(x["published_at"]).date()).days <= 7]:
        txt += [f"- {n['published_at'][:10]} | {n['region']} | {n['title']}: {n['summary']}"]
    txt += ["", LABEL]
    (DOC_DIR / "Weekly_Rice_Market_News.txt").write_text("\n".join(txt), encoding="utf-8")

    # 12. Trend report (Excel)
    import pandas as pd
    trend_rows = []
    for p in PRODUCTS:
        for city in LOWER_PUNJAB + ["Karachi"]:
            r = latest_and_change(prices, p.key, city, 7)
            if not r:
                continue
            r15, r30 = latest_and_change(prices, p.key, city, 15), latest_and_change(prices, p.key, city, 30)
            trend_rows.append({"product": p.name, "variety": p.variety, "grade": p.grade, "city": city,
                               "unit": r[0]["unit"], "latest_price": r[0]["price"], "latest_date": r[0]["observed_at"][:10],
                               "change_7d_pct": None if r[2] is None else round(r[2], 2),
                               "change_15d_pct": None if r15[2] is None else round(r15[2], 2),
                               "change_30d_pct": None if r30[2] is None else round(r30[2], 2),
                               "direction_7d": direction(r[2]), "data_label": "SYNTHETIC"})
    with pd.ExcelWriter(DOC_DIR / "Rice_Price_Trend_Report.xlsx") as xw:
        pd.DataFrame(trend_rows).to_excel(xw, sheet_name="Trends", index=False)
        pd.DataFrame([{"note": LABEL}]).to_excel(xw, sheet_name="README", index=False)


def main() -> None:
    rng = random.Random(SEED)
    prices = generate_prices(rng)
    quotes = generate_quotations(rng, prices)
    news = generate_news()
    write_csv(SYN_DIR / "synthetic_market_prices.csv", prices)
    write_csv(SYN_DIR / "synthetic_broker_quotations.csv", quotes)
    write_csv(SYN_DIR / "synthetic_news_articles.csv", news)
    (SYN_DIR / "README.md").write_text(
        f"# Synthetic data\n\n**{LABEL}.**\n\nGenerated by `scripts/generate_synthetic_data.py` (seed {SEED}, "
        f"last observation date {END_DATE}). These CSVs seed the SQLite database in demo mode.\n", encoding="utf-8")
    build_documents(prices, quotes, news)
    # sample authorised-import template
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(SAMPLE_DIR / "price_import_template.csv", [{
        "product_key": "paddy_1121_basmati", "product_name": "1121 Basmati Paddy", "product_type": "paddy",
        "variety": "1121 Basmati", "grade": "Standard (moisture <=16%)", "market": "Multan Grain Market",
        "city": "Multan", "province": "Punjab", "country": "Pakistan", "price": "0", "currency": "PKR",
        "unit": "PKR/40kg", "price_category": "wholesale", "observed_at": "2026-11-11T10:00:00",
        "source_name": "REPLACE WITH YOUR AUTHORISED SOURCE", "source_url": "", "verification_status": "unverified",
    }])
    print(f"Generated {len(prices)} price rows, {len(quotes)} quotations, {len(news)} news items.")
    print(f"Documents: {sorted(p.name for p in DOC_DIR.iterdir())}")


if __name__ == "__main__":
    main()

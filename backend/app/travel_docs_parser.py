"""
Leitura e comparação cruzada de documentos de tripulação/passageiros:
GenDec (GEDEC), eAPIS e eGAR (Reino Unido).

Cada documento é lido e reduzido a uma lista de pessoas (nome, nacionalidade,
número de documento, data de nascimento). As pessoas são então casadas entre
os documentos (por data de nascimento e, na falta dela, por sobreposição de
nome) para apontar divergências — ex: mesmo número de documento diferente
entre dois formulários, ou uma pessoa presente em um documento e ausente em
outro.

GEDEC e eAPIS têm texto extraível normalmente. O eGAR (Reino Unido) é
tipicamente gerado via "imprimir em PDF" a partir do navegador e não tem
texto algum incorporado — o conteúdo é lido via OCR (pytesseract) sobre a
página renderizada. OCR é best effort: dígitos/letras parecidos (0/O, 1/I)
podem ser confundidos, então todo dado vindo de OCR é marcado com
`"ocr": true` para o frontend exibir um aviso e o número original do
documento sempre deve ser conferido visualmente em caso de divergência.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from io import BytesIO

import pdfplumber

# pypdfium2/pytesseract só são importados dentro de parse_egar() (import
# tardio) — são as únicas funções que precisam deles. Importar no topo do
# módulo carregaria essas bibliotecas (+ o binário tesseract-ocr por trás)
# na memória de TODO request, mesmo os que não leem eGAR nenhum, o que é
# desperdício de memória no plano free do Render (512MB) e pode derrubar o
# processo com OOM em requests que nem usam OCR.

# ---------------------------------------------------------------------------
# Modelo comum
# ---------------------------------------------------------------------------


@dataclass
class Person:
    doc_source: str  # "GEDEC" | "eAPIS" | "eGAR"
    role: str | None  # PIC/SIC/FA/Pilot/Cabin/Passenger/Crew/Captain etc (texto original)
    name: str
    nationality: str | None
    document_number: str | None
    dob_raw: str | None
    dob_iso: str | None = None
    ocr: bool = False
    ocr_uncertain: bool = False


def _normalize_date(raw: str | None, fmt: str) -> tuple[str | None, bool]:
    """Retorna (iso ou None, incerto). fmt: 'dd_mon_yyyy' | 'mon_dd_yyyy' | 'yyyy_mm_dd'."""
    if not raw:
        return None, False
    raw = raw.strip()
    try:
        if fmt == "dd_mon_yyyy":
            dt = datetime.strptime(raw, "%d %b %Y")
        elif fmt == "mon_dd_yyyy":
            dt = datetime.strptime(raw, "%b %d %Y")
        elif fmt == "yyyy_mm_dd":
            dt = datetime.strptime(raw, "%Y-%m-%d")
        else:
            return None, True
        return dt.date().isoformat(), False
    except ValueError:
        return None, True


# ---------------------------------------------------------------------------
# GEDEC (General Declaration)
# ---------------------------------------------------------------------------

_GEDEC_RANKS = "PIC|SIC|FO|FA|CPT|CA|PU|FE|NAV"
_GEDEC_CREW_RE = re.compile(
    rf"^(?P<name>[A-ZÀ-Ÿ' ]+?)\s+(?P<rank>{_GEDEC_RANKS})\s+(?P<nat>[A-Z]{{3}})\s+"
    rf"(?P<exp>\d{{1,2}}\s\w{{3}}\s\d{{4}})\s+(?P<doc>\S+)\s+"
    rf"(?P<dob>\d{{1,2}}\s\w{{3}}\s\d{{4}})\s+(?P<license>\S+)\s*$"
)
_GEDEC_PAX_RE = re.compile(
    r"^(?P<name>[A-ZÀ-Ÿ' ]+?)\s+(?P<nat>[A-Z]{3})\s+"
    r"(?P<exp>\d{1,2}\s\w{3}\s\d{4})\s+(?P<doc>\S+)\s+"
    r"(?P<dob>\d{1,2}\s\w{3}\s\d{4})\s*$"
)


def parse_gedec(pdf_bytes: bytes) -> dict:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text(layout=False) or "") for p in pdf.pages)

    header: dict = {}
    for label, pattern in (
        ("operator", r"OPERATOR:\s*(.+)"),
        ("registration", r"MARKS OF REGISTRATION:\s*(\S+)"),
        ("aircraft_type", r"AIRCRAFT TYPE:\s*(\S+)"),
        ("departure_airport", r"AIRPORT OF DEPARTURE:\s*(.+)"),
        ("arrival_airport", r"AIRPORT OF ARRIVAL:\s*(.+)"),
        ("departure_date", r"DEPARTURE DATE:\s*([\d\w ]+?)\s*\("),
    ):
        m = re.search(pattern, text)
        if m:
            header[label] = m.group(1).strip()

    manifest_split = re.split(r"PASSENGER MANIFEST", text, maxsplit=1)
    crew_section = manifest_split[0]
    pax_section = manifest_split[1] if len(manifest_split) > 1 else ""
    pax_section = re.split(r"I declare", pax_section, maxsplit=1)[0]

    people: list[Person] = []
    for line in crew_section.split("\n"):
        m = _GEDEC_CREW_RE.match(line.strip())
        if m:
            g = m.groupdict()
            dob_iso, uncertain = _normalize_date(g["dob"], "dd_mon_yyyy")
            people.append(
                Person(
                    doc_source="GEDEC",
                    role=g["rank"],
                    name=g["name"].strip(),
                    nationality=g["nat"],
                    document_number=g["doc"],
                    dob_raw=g["dob"],
                    dob_iso=dob_iso,
                    ocr_uncertain=uncertain,
                )
            )

    for line in pax_section.split("\n"):
        m = _GEDEC_PAX_RE.match(line.strip())
        if m:
            g = m.groupdict()
            dob_iso, uncertain = _normalize_date(g["dob"], "dd_mon_yyyy")
            people.append(
                Person(
                    doc_source="GEDEC",
                    role="PAX",
                    name=g["name"].strip(),
                    nationality=g["nat"],
                    document_number=g["doc"],
                    dob_raw=g["dob"],
                    dob_iso=dob_iso,
                    ocr_uncertain=uncertain,
                )
            )

    return {"header": header, "people": [asdict(p) for p in people]}


# ---------------------------------------------------------------------------
# eAPIS
# ---------------------------------------------------------------------------

_EAPIS_ROLES = r"Pilot|Cabin|Captain|First Officer|Flight Attendant|Second Officer|Purser|Load Master"
_EAPIS_ROLE_RE = re.compile(rf"^({_EAPIS_ROLES})\b")
_EAPIS_CREW_LINE1_RE = re.compile(
    rf"^(?P<role>{_EAPIS_ROLES})\s+"
    r"(?P<name>.+?)\s+(?P<dob>[A-Z][a-z]{2}\s\d{2}\s\d{4})\s+(?P<gender>[MF])\s+"
    r"(?P<citizenship>\S+)\s+(?P<doctypes>.+)$"
)
_EAPIS_PAX_LINE1_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<dob>[A-Z][a-z]{2}\s\d{2}\s\d{4})\s+(?P<gender>[MF])\s+"
    r"(?P<citizenship>\S+)\s+(?P<doctypes>.+)$"
)


def _parse_eapis_block(lines: list[str], is_crew: bool) -> list[dict]:
    line1_re = _EAPIS_CREW_LINE1_RE if is_crew else _EAPIS_PAX_LINE1_RE
    records = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        m1 = line1_re.match(line)
        if not m1:
            i += 1
            continue
        rec = m1.groupdict()
        i += 1
        docnums: list[str] = []
        if i < n and not lines[i].strip().startswith("EXP:") and not _EAPIS_ROLE_RE.match(lines[i].strip()):
            docnums = lines[i].strip().split()
            i += 1
        while i < n and lines[i].strip().startswith("EXP:"):
            i += 1
        while i < n and re.match(r"^[A-Z]{2,3}$", lines[i].strip()):
            i += 1
        rec["doc_numbers"] = docnums
        records.append(rec)
    return records


def parse_eapis(pdf_bytes: bytes) -> dict:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text(layout=False) or "") for p in pdf.pages)

    header: dict = {}
    reg_m = re.search(r"Aircraft Registration\s+(\S+)", text)
    if reg_m:
        header["registration"] = reg_m.group(1)

    people: list[Person] = []

    crew_m = re.search(r"CREW\n(.*?)(?=\nPASSENGERS|\Z)", text, re.S)
    if crew_m:
        crew_lines = [l for l in crew_m.group(1).split("\n") if not l.startswith("Role Name")]
        for rec in _parse_eapis_block(crew_lines, is_crew=True):
            dob_iso, uncertain = _normalize_date(rec["dob"], "mon_dd_yyyy")
            docnums = rec["doc_numbers"]
            people.append(
                Person(
                    doc_source="eAPIS",
                    role=rec["role"],
                    name=rec["name"].strip(),
                    nationality=(rec["citizenship"].split("/")[-1] if rec.get("citizenship") else None),
                    document_number=docnums[0] if docnums else None,
                    dob_raw=rec["dob"],
                    dob_iso=dob_iso,
                    ocr_uncertain=uncertain,
                )
            )

    pax_m = re.search(r"PASSENGERS\n(.*?)\Z", text, re.S)
    if pax_m:
        pax_lines = [l for l in pax_m.group(1).split("\n") if not l.startswith("Name Date")]
        for rec in _parse_eapis_block(pax_lines, is_crew=False):
            dob_iso, uncertain = _normalize_date(rec["dob"], "mon_dd_yyyy")
            docnums = rec["doc_numbers"]
            people.append(
                Person(
                    doc_source="eAPIS",
                    role="Passenger",
                    name=rec["name"].strip(),
                    nationality=(rec["citizenship"].split("/")[-1] if rec.get("citizenship") else None),
                    document_number=docnums[0] if docnums else None,
                    dob_raw=rec["dob"],
                    dob_iso=dob_iso,
                    ocr_uncertain=uncertain,
                )
            )

    return {"header": header, "people": [asdict(p) for p in people]}


# ---------------------------------------------------------------------------
# Lista de passageiros (formato "Voo NNN ... / Lista de Passageiros")
# ---------------------------------------------------------------------------
# Documento costuma ter várias páginas extras com fotos de passaporte
# escaneadas (uma por página) — só a primeira página, com a tabela de
# texto, é usada aqui; as páginas de imagem são ignoradas (não têm dados
# adicionais além da conferência visual do passaporte, que fica fora do
# escopo desta comparação automática).

_PAXLIST_ROW_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<dob>\d{1,2}\s\w{3}\s\d{4})\s+"
    r"(?P<nat>[A-Z]{3}):\s+(?P<doc>\S+)\s+\((?P<exp>\d{1,2}\s\w{3}\s\d{4})\)\s*$"
)


def parse_passenger_list(pdf_bytes: bytes) -> dict:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        text = pdf.pages[0].extract_text(layout=False) or ""

    header: dict = {}
    flight_m = re.search(r"Voo\s+(\S+)\s+(.+)", text)
    if flight_m:
        header["flight_number"] = flight_m.group(1)
        header["operator"] = flight_m.group(2).strip()
    dep_m = re.search(r"DEP\s+(.+)", text)
    if dep_m:
        header["departure"] = dep_m.group(1).strip()
    arr_m = re.search(r"ARR\s+(.+)", text)
    if arr_m:
        header["arrival"] = arr_m.group(1).strip()

    people: list[Person] = []
    for line in text.split("\n"):
        m = _PAXLIST_ROW_RE.match(line.strip())
        if not m:
            continue
        g = m.groupdict()
        dob_iso, uncertain = _normalize_date(g["dob"], "dd_mon_yyyy")
        people.append(
            Person(
                doc_source="Lista de passageiros",
                role="Passenger",
                name=g["name"].strip(),
                nationality=g["nat"],
                document_number=g["doc"],
                dob_raw=g["dob"],
                dob_iso=dob_iso,
                ocr_uncertain=uncertain,
            )
        )

    return {"header": header, "people": [asdict(p) for p in people]}


# ---------------------------------------------------------------------------
# eGAR (Reino Unido) — sem texto incorporado, lido via OCR
# ---------------------------------------------------------------------------

_EGAR_HEADER_LABELS = ["Surname", "Given", "Nationality", "Document", "Sex", "Place", "Type"]
_EGAR_TYPE_VOCAB = {"crew", "captain", "passenger", "pic", "sic", "fa", "pilot"}
_EGAR_NOISE_RE = re.compile(r"^[a-zA-Z]{0,3}[:.]$")


def _egar_ocr_words(pdf_bytes: bytes, scale: int = 3):
    import pypdfium2 as pdfium
    import pytesseract
    from pytesseract import Output

    doc = pdfium.PdfDocument(BytesIO(pdf_bytes))
    page = doc[0]
    image = page.render(scale=scale).to_pil()
    ocr = pytesseract.image_to_data(image, output_type=Output.DICT)
    words = []
    for i in range(len(ocr["text"])):
        t = ocr["text"][i].strip()
        if t:
            words.append({"text": t, "left": ocr["left"][i], "top": ocr["top"][i]})
    return words


def _egar_table_rows(pdf_bytes: bytes, words: list[dict], scale: int) -> list[float]:
    header_words = sorted(
        [w for w in words if w["text"] in _EGAR_HEADER_LABELS], key=lambda w: w["left"]
    )
    if not header_words:
        return []
    header_top_pt = min(w["top"] for w in header_words) / scale

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        p = pdf.pages[0]
        horiz = [r for r in p.rects if r["width"] > 100 and r["height"] < 3]
        horiz.sort(key=lambda r: r["top"])
        table_lines = [r for r in horiz if r["top"] >= header_top_pt - 5]
        if not table_lines:
            return []
        base_w = round(table_lines[0]["width"], 0)
        row_lines = []
        for r in table_lines:
            if abs(r["width"] - base_w) < 2:
                row_lines.append(r["top"])
            else:
                break
    return row_lines


def _egar_column_bounds(words: list[dict], scale: int):
    header_words = sorted(
        [w for w in words if w["text"] in _EGAR_HEADER_LABELS], key=lambda w: w["left"]
    )
    positions: dict[str, float] = {}
    doc_seen = 0
    for w in header_words:
        label = w["text"]
        if label == "Document":
            doc_seen += 1
            label = "DocNumber" if doc_seen == 1 else "DocExpiry"
        positions.setdefault(label, w["left"] / scale)

    required = ["Surname", "Given", "Nationality", "DocNumber", "DocExpiry", "Sex", "Place", "Type"]
    if not all(k in positions for k in required):
        return None

    positions_full = {
        "surname": positions["Surname"],
        "given_names": positions["Given"],
        "dob": positions["Given"] + (positions["Nationality"] - positions["Given"]) * 0.45,
        "nationality": positions["Nationality"],
        "doc_number": positions["DocNumber"],
        "doc_expiry": positions["DocExpiry"],
        "sex": positions["Sex"],
        "place_of_birth": positions["Place"],
        "type": positions["Type"],
    }
    ordered = sorted(positions_full.items(), key=lambda kv: kv[1])
    bounds = []
    for idx, (name, x) in enumerate(ordered):
        lo = x - 15 if idx == 0 else (ordered[idx - 1][1] + x) / 2
        bounds.append((name, lo))
    bounds.append(("__end__", 10**9))
    return bounds


def _col_for_x(bounds, x_pt: float) -> str:
    for i in range(len(bounds) - 1):
        if bounds[i][1] <= x_pt < bounds[i + 1][1]:
            return bounds[i][0]
    return bounds[-2][0]


def parse_egar(pdf_bytes: bytes) -> dict:
    scale = 3
    words = _egar_ocr_words(pdf_bytes, scale)

    header: dict = {}
    reg_words = [w for w in words if w["text"] == "PSSRN"]  # fallback, overwritten below if found properly
    id_m = re.search(r"[A-Za-z0-9_]+eGAR", " ".join(w["text"] for w in words))

    bounds = _egar_column_bounds(words, scale)
    row_lines = _egar_table_rows(pdf_bytes, words, scale)

    people: list[Person] = []
    if bounds and len(row_lines) >= 2:
        for i in range(len(row_lines) - 1):
            top_px, bot_px = row_lines[i] * scale, row_lines[i + 1] * scale
            row_words = [w for w in words if top_px <= w["top"] < bot_px]
            cols: dict[str, list[dict]] = {}
            for w in row_words:
                c = _col_for_x(bounds, w["left"] / scale)
                cols.setdefault(c, []).append(w)
            for c in cols:
                cols[c].sort(key=lambda w: w["top"])

            type_words = cols.get("type", [])
            real_type = [w for w in type_words if w["text"].lower().strip(".,:") in _EGAR_TYPE_VOCAB]
            spill = [w for w in type_words if w not in real_type]
            cols["place_of_birth"] = cols.get("place_of_birth", []) + spill
            cols["place_of_birth"].sort(key=lambda w: w["top"])
            cols["type"] = real_type

            def join(colname: str, is_date: bool = False) -> str:
                ws = [w for w in cols.get(colname, []) if not _EGAR_NOISE_RE.match(w["text"])]
                ws = [w for w in ws if re.search(r"[A-Za-z0-9]", w["text"])]
                sep = "" if is_date else " "
                return sep.join(w["text"] for w in ws).strip()

            surname = join("surname")
            given_names = join("given_names")
            dob_raw = join("dob", is_date=True)
            nationality = join("nationality")
            doc_number = join("doc_number", is_date=True)
            doc_type = join("type")

            if not (surname or given_names):
                continue

            dob_iso, uncertain = _normalize_date(dob_raw, "yyyy_mm_dd")

            people.append(
                Person(
                    doc_source="eGAR",
                    role=doc_type or None,
                    name=f"{given_names} {surname}".strip(),
                    nationality=nationality or None,
                    document_number=doc_number or None,
                    dob_raw=dob_raw or None,
                    dob_iso=dob_iso,
                    ocr=True,
                    ocr_uncertain=uncertain,
                )
            )

    if id_m:
        header["gar_id"] = id_m.group(0)

    return {"header": header, "people": [asdict(p) for p in people]}


# ---------------------------------------------------------------------------
# Comparação cruzada
# ---------------------------------------------------------------------------

_COMPARE_FIELDS = ["name", "nationality", "document_number", "dob_iso"]


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _name_tokens(name: str | None) -> set[str]:
    """Tokeniza um nome pra comparação — maiúsculas e sem acento, pra não
    marcar como divergência algo que é só diferença de grafia entre
    documentos (ex: GEDEC em CAIXA ALTA sem acento "JOAO" vs a lista de
    passageiros com acento "João")."""
    if not name:
        return set()
    cleaned = re.sub(r"[^A-Z ]", "", _strip_accents(name.upper()))
    return set(t for t in cleaned.split() if len(t) > 1)


def _normalized_value(field: str, value):
    """Normaliza um valor de campo só para fins de comparação (detectar
    divergência), sem alterar o valor exibido. 'name' ignora
    maiúsculas/minúsculas e ordem das palavras (ex: GEDEC está em CAIXA
    ALTA e a ordem pode variar) — só é considerado diferente se o conjunto
    de palavras do nome realmente mudar."""
    if value is None:
        return None
    if field == "name":
        return frozenset(_name_tokens(value))
    if isinstance(value, str):
        return value.strip().upper()
    return value


def compare_people(people_by_doc: dict[str, list[dict]]) -> list[dict]:
    """Casa pessoas entre documentos (por DOB, com fallback por sobreposição
    de nome) e aponta divergências de nacionalidade/documento/nome/DOB, além
    de quem está ausente em algum documento."""
    flat: list[dict] = []
    for doc_name, people in people_by_doc.items():
        for p in people:
            flat.append({**p, "_doc": doc_name})

    used = [False] * len(flat)
    groups: list[list[dict]] = []

    for i, p in enumerate(flat):
        if used[i]:
            continue
        group = [p]
        used[i] = True
        p_tokens = _name_tokens(p.get("name"))
        p_dob = p.get("dob_iso")
        for j in range(i + 1, len(flat)):
            if used[j]:
                continue
            q = flat[j]
            if q["_doc"] == p["_doc"]:
                continue
            q_dob = q.get("dob_iso")
            if p_dob and q_dob:
                # Os dois lados têm data de nascimento — é o sinal mais
                # confiável que temos, então a decisão é só dele. Importante
                # NÃO cair pro nome quando as datas são conhecidas e
                # diferentes: parentes com sobrenome em comum (ex: "MARIA
                # ROLIM MACHADO" x "JOAO ROLIM MACHADO") facilmente batem
                # >=50% de sobreposição de palavras e seriam misturados
                # como se fossem a mesma pessoa.
                match = p_dob == q_dob
            else:
                # Pelo menos um lado sem DOB (ex: falha de OCR/parse) — só
                # resta comparar nomes, com o risco de falso positivo entre
                # parentes descrito acima.
                q_tokens = _name_tokens(q.get("name"))
                match = bool(p_tokens and q_tokens) and (
                    len(p_tokens & q_tokens) / max(1, len(p_tokens | q_tokens)) >= 0.5
                )
            if match:
                group.append(q)
                used[j] = True
        groups.append(group)

    all_docs = list(people_by_doc.keys())
    comparisons = []
    for group in groups:
        docs_present = sorted({g["_doc"] for g in group})
        mismatched_fields = []
        for f in _COMPARE_FIELDS:
            values = {g["_doc"]: g.get(f) for g in group}
            distinct = {_normalized_value(f, v) for v in values.values() if v}
            if len(distinct) > 1:
                mismatched_fields.append(f)
        comparisons.append(
            {
                "people": group,
                "docs_present": docs_present,
                "missing_from": [d for d in all_docs if d not in docs_present],
                "mismatched_fields": mismatched_fields,
                "has_issue": bool(mismatched_fields) or len(all_docs) > len(docs_present),
            }
        )

    comparisons.sort(key=lambda c: (-len(c["mismatched_fields"]), -len(c["missing_from"])))
    return comparisons


def build_docs_summary(files: dict[str, bytes]) -> dict:
    """files: dict com chaves opcionais 'gedec', 'eapis', 'egar',
    'passenger_list' -> bytes do PDF."""
    people_by_doc: dict[str, list[dict]] = {}
    docs_info: dict[str, dict] = {}

    if files.get("gedec"):
        result = parse_gedec(files["gedec"])
        people_by_doc["GEDEC"] = result["people"]
        docs_info["GEDEC"] = result["header"]

    if files.get("eapis"):
        result = parse_eapis(files["eapis"])
        people_by_doc["eAPIS"] = result["people"]
        docs_info["eAPIS"] = result["header"]

    if files.get("egar"):
        result = parse_egar(files["egar"])
        people_by_doc["eGAR"] = result["people"]
        docs_info["eGAR"] = result["header"]

    if files.get("passenger_list"):
        result = parse_passenger_list(files["passenger_list"])
        people_by_doc["Lista de passageiros"] = result["people"]
        docs_info["Lista de passageiros"] = result["header"]

    comparison = compare_people(people_by_doc) if people_by_doc else []

    return {
        "docs_info": docs_info,
        "people_by_doc": people_by_doc,
        "comparison": comparison,
        "has_ocr": any(p.get("ocr") for people in people_by_doc.values() for p in people),
    }

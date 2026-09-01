"""Import d'une liste de leads depuis un fichier Excel/CSV (source `kind='import'`).

Troisième porte d'entrée de la prospection, après les commentateurs d'un post
concurrent (`kind='post'`) et l'import d'une recherche LinkedIn (`kind='search'`,
0062) : le client téléverse un export (CRM, outil Sales Navigator tiers,
tableur maison) et toutes les lignes portant une URL de profil LinkedIn
deviennent des leads — dédupliqués et notés par le ciblage ICP comme les autres.

On RÉUTILISE toute la machinerie existante plutôt que d'en dupliquer une :
`lead_sources` (avec `kind='import'`, migration 0070), `lead_collection_jobs`
(polling frontend inchangé), `db.save_leads` (canonicalisation + dédup par
personne), `_score_leads_for_source` (scoring ICP best-effort). Import gratuit
(aucun crédit) : lire un fichier ne coûte rien, comme la recherche Unipile.

⚠️ Parsing xlsx en stdlib (zipfile + xml.etree), PAS openpyxl : le repo évite
les dépendances (tout le réseau est en urllib). Un .xlsx est un zip de XML dont
on ne lit que deux membres (feuille 1 + chaînes partagées) — largement assez
pour une liste de leads. Un fichier illisible reçoit un 422 clair qui renvoie
vers l'export CSV, jamais un import vide silencieux.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
import zipfile
from typing import Any
from xml.etree import ElementTree

from src.lead_search import canonical_profile_url


class LeadImportError(ValueError):
    """Fichier de leads inexploitable (message destiné au client)."""


# Plafond de taille : une liste de leads tient très largement dans 5 Mo
# (≈ 30 000 lignes de CSV). Au-delà, c'est presque sûrement le mauvais fichier.
MAX_FILE_BYTES = 5 * 1024 * 1024

# Garde-fou volume par import — au-dessus du plafond de la recherche (1000,
# celui de LinkedIn) car un fichier peut légitimement en porter plus, mais borné
# quand même : le scoring ICP et l'écran de prospection ne sont pas conçus pour
# des dizaines de milliers de lignes d'un coup.
MAX_LEADS = 2000

_XLSX_MAGIC = b"PK\x03\x04"
_XLS_MAGIC = b"\xd0\xcf\x11\xe0"  # vieux .xls binaire (OLE2) — non supporté

# Garde anti zip-bomb : taille décompressée maximale d'un membre XML du .xlsx.
# Le fichier vient d'un utilisateur authentifié mais reste une entrée non fiable
# — un zip de 5 Mo peut se décompresser en gigaoctets. (Le repo étant
# stdlib-only, on ne tire pas defusedxml ; ElementTree ne résout de toute façon
# pas les entités externes, et cette borne coupe l'amplification mémoire.)
_MAX_XML_MEMBER_BYTES = 30 * 1024 * 1024


def _norm_header(value: str) -> str:
    """Normalise un en-tête de colonne : accents retirés, casse/espaces ignorés."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text.lower())


# En-têtes reconnus (forme normalisée) pour les colonnes optionnelles. La
# colonne d'URL, elle, est détectée PAR SON CONTENU (cf. `_url_column`) : c'est
# plus fiable que n'importe quelle liste de synonymes, et ça couvre les fichiers
# sans en-tête du tout.
_FULL_NAME_HEADERS = {"name", "fullname", "nomcomplet", "nom", "contact", "personne", "prospect"}
_FIRST_NAME_HEADERS = {"firstname", "prenom", "first", "givenname"}
_LAST_NAME_HEADERS = {"lastname", "nom", "nomdefamille", "last", "surname", "familyname"}
_TITLE_HEADERS = {
    "headline", "title", "jobtitle", "titre", "poste", "fonction", "position",
    "intitule", "intituledeposte", "occupation", "role",
}
_COMPANY_HEADERS = {
    "company", "entreprise", "societe", "organisation", "organization",
    "companyname", "currentcompany", "nomdelentreprise", "boite",
}


def import_source_key(data: bytes) -> str:
    """Clé synthétique de la source, dérivée du CONTENU du fichier.

    Stockée dans `lead_sources.post_url` (contrainte d'unicité user+post_url) :
    ré-importer le même fichier retombe sur la même source au lieu d'en créer
    une deuxième — même dédup naturelle que la recherche (0062).
    """
    return "import://" + hashlib.sha256(data).hexdigest()[:20]


def is_import_source_key(url: str | None) -> bool:
    return bool(url) and str(url).startswith("import://")


# --------------------------------------------------------------------------- #
# Lecture du fichier → grille de cellules
# --------------------------------------------------------------------------- #

def _decode_text(data: bytes) -> str:
    """Décode un CSV en tolérant les exports Excel français (BOM, cp1252)."""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    # latin-1 ne peut pas échouer, mais restons défensifs.
    return data.decode("utf-8", errors="replace")


def _parse_csv(data: bytes) -> list[list[str]]:
    text = _decode_text(data)
    sample = text[:4096]
    # Excel FR exporte en `;`, les outils anglo-saxons en `,` : on renifle le
    # séparateur au lieu de l'imposer. En cas d'échec du sniffer, majorité
    # simple sur la première ligne.
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        first_line = sample.splitlines()[0] if sample.splitlines() else ""
        delimiter = max(",;\t", key=first_line.count) if first_line else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[cell.strip() for cell in row] for row in reader]


def _local(tag: str) -> str:
    """Nom local d'un tag XML (namespace spreadsheetml ignoré)."""
    return tag.rsplit("}", 1)[-1]


def _cell_ref_to_index(ref: str | None) -> int | None:
    """`B7` → 1. None si la référence est absente/illisible."""
    if not ref:
        return None
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    if not letters:
        return None
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


def _read_xml_member(zf: zipfile.ZipFile, name: str) -> bytes:
    """Lit un membre XML du zip en refusant une décompression démesurée."""
    try:
        if zf.getinfo(name).file_size > _MAX_XML_MEMBER_BYTES:
            raise LeadImportError(
                "Fichier Excel anormalement gros une fois décompressé — exporte ta liste en CSV."
            )
    except KeyError as exc:
        raise LeadImportError("Fichier Excel illisible — exporte ta liste en CSV.") from exc
    return zf.read(name)


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ElementTree.fromstring(_read_xml_member(zf, "xl/sharedStrings.xml"))
    strings: list[str] = []
    for si in root:
        if _local(si.tag) != "si":
            continue
        # Un `si` peut porter un <t> simple ou des runs riches <r><t> : on
        # concatène tous les fragments de texte descendants.
        strings.append("".join(node.text or "" for node in si.iter() if _local(node.tag) == "t"))
    return strings


def _parse_xlsx(data: bytes) -> list[list[str]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise LeadImportError(
            "Fichier Excel illisible. Ré-enregistre-le au format .xlsx, ou exporte-le en CSV."
        ) from exc
    names = zf.namelist()
    sheets = sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
    if not sheets:
        raise LeadImportError(
            "Ce fichier ne contient aucune feuille Excel lisible. Exporte ta liste en CSV et réessaie."
        )
    # Première feuille : le cas réel d'une liste de leads. (Lire l'ordre exact du
    # classeur exigerait workbook.xml + ses relations — hors de proportion ici.)
    sheet = "xl/worksheets/sheet1.xml" if "xl/worksheets/sheet1.xml" in names else sheets[0]
    try:
        root = ElementTree.fromstring(_read_xml_member(zf, sheet))
        shared = _xlsx_shared_strings(zf)
    except ElementTree.ParseError as exc:
        raise LeadImportError(
            "Fichier Excel illisible. Ré-enregistre-le au format .xlsx, ou exporte-le en CSV."
        ) from exc

    rows: list[list[str]] = []
    for row_el in root.iter():
        if _local(row_el.tag) != "row":
            continue
        cells: list[str] = []
        position = 0
        for cell in row_el:
            if _local(cell.tag) != "c":
                continue
            index = _cell_ref_to_index(cell.get("r"))
            if index is None:
                index = position
            ctype = cell.get("t") or ""
            value = ""
            if ctype == "inlineStr":
                value = "".join(n.text or "" for n in cell.iter() if _local(n.tag) == "t")
            else:
                for child in cell:
                    if _local(child.tag) == "v":
                        value = child.text or ""
                        break
                if ctype == "s":
                    try:
                        value = shared[int(value)]
                    except (ValueError, IndexError):
                        value = ""
            while len(cells) <= index:
                cells.append("")
            cells[index] = str(value).strip()
            position = index + 1
        rows.append(cells)
    return rows


def _read_rows(filename: str | None, data: bytes) -> list[list[str]]:
    """Grille de cellules depuis le fichier, quel que soit son format."""
    if not data:
        raise LeadImportError("Le fichier est vide.")
    if len(data) > MAX_FILE_BYTES:
        mb = MAX_FILE_BYTES // (1024 * 1024)
        raise LeadImportError(
            f"Fichier trop volumineux ({mb} Mo maximum). Découpe ta liste ou exporte-la en CSV."
        )
    if data[:4] == _XLS_MAGIC:
        raise LeadImportError(
            "L'ancien format .xls n'est pas supporté. Ré-enregistre le fichier en .xlsx, "
            "ou exporte-le en CSV."
        )
    name = (filename or "").lower()
    # Le contenu prime sur l'extension : un .csv renommé .xlsx (ou l'inverse)
    # arrive plus souvent qu'on ne croit.
    if data[:4] == _XLSX_MAGIC or name.endswith((".xlsx", ".xlsm")):
        return _parse_xlsx(data)
    return _parse_csv(data)


# --------------------------------------------------------------------------- #
# Grille de cellules → leads persistables
# --------------------------------------------------------------------------- #

def _url_column(rows: list[list[str]]) -> int | None:
    """Colonne portant les URLs de profil, détectée PAR LE CONTENU.

    Plus fiable qu'une liste d'en-têtes : couvre les fichiers sans en-tête, les
    intitulés exotiques, et écarte d'office les colonnes d'URLs d'ENTREPRISE
    (`/company/…` ne canonicalise pas en profil).
    """
    counts: dict[int, int] = {}
    for row in rows:
        for i, cell in enumerate(row):
            if cell and canonical_profile_url(cell):
                counts[i] = counts.get(i, 0) + 1
    if not counts:
        return None
    best = max(counts.values())
    return min(i for i, n in counts.items() if n == best)


def _header_index(headers: list[str], names: set[str]) -> int | None:
    for i, h in enumerate(headers):
        if h in names:
            return i
    return None


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return (row[index] or "").strip()


def parse_leads_file(filename: str | None, data: bytes) -> dict[str, Any]:
    """Extrait les leads d'un fichier CSV/xlsx.

    Retourne {leads, ignored, rows, truncated} :
    - `leads` : dicts persistables par `db.save_leads` (URL canonique, dédup
      intra-fichier par personne, nom/headline si les colonnes existent) ;
    - `ignored` : lignes NON VIDES sans URL de profil LinkedIn valide — comptées
      et restituées au client (« 13 lignes ignorées ») plutôt qu'avalées ;
    - `rows` : lignes de données non vides examinées ;
    - `truncated` : True si le fichier dépassait `MAX_LEADS`.

    Lève `LeadImportError` (message client) si rien n'est exploitable.
    """
    grid = _read_rows(filename, data)
    filled = [row for row in grid if any((cell or "").strip() for cell in row)]
    if not filled:
        raise LeadImportError("Le fichier ne contient aucune ligne de données.")

    # Ligne d'en-tête = première ligne SI elle ne porte pas déjà une URL de
    # profil (un fichier sans en-tête commence directement par les données).
    first = filled[0]
    has_header = not any(canonical_profile_url(cell) for cell in first if cell)
    headers = [_norm_header(cell) for cell in first] if has_header else []
    data_rows = filled[1:] if has_header else filled

    if not data_rows:
        raise LeadImportError(
            "Le fichier ne contient que des en-têtes — aucune ligne de prospect."
        )

    url_col = _url_column(data_rows)
    full_name_col = _header_index(headers, _FULL_NAME_HEADERS)
    first_name_col = _header_index(headers, _FIRST_NAME_HEADERS)
    last_name_col = _header_index(headers, _LAST_NAME_HEADERS)
    # « nom » seul est un nom COMPLET en français ; accompagné d'un « prénom »,
    # c'est un nom de famille. On ne le lit en nom complet que sans prénom à côté.
    if first_name_col is not None and last_name_col == full_name_col:
        full_name_col = None
    title_col = _header_index(headers, _TITLE_HEADERS)
    company_col = _header_index(headers, _COMPANY_HEADERS)

    leads: list[dict[str, Any]] = []
    seen: set[str] = set()
    ignored = 0
    truncated = False
    for row in data_rows:
        url = canonical_profile_url(_cell(row, url_col)) if url_col is not None else None
        if not url:
            # Fichier hétérogène : l'URL peut vivre dans une autre colonne sur
            # certaines lignes. On balaie la ligne avant de l'ignorer.
            url = next((canonical_profile_url(c) for c in row if c and canonical_profile_url(c)), None)
        if not url:
            ignored += 1
            continue
        if url in seen:
            continue  # doublon intra-fichier : une personne = un lead
        if len(leads) >= MAX_LEADS:
            truncated = True
            break
        seen.add(url)

        name = _cell(row, full_name_col)
        if not name:
            name = " ".join(p for p in (_cell(row, first_name_col), _cell(row, last_name_col)) if p)
        title = _cell(row, title_col)
        company = _cell(row, company_col)
        headline = title
        if company and _norm_header(company) not in _norm_header(title):
            headline = f"{title} · {company}" if title else company

        leads.append(
            {
                "name": name[:300] or None,
                "headline": headline[:500] or None,
                "profile_url": url,
                "provider_id": None,
                # Un lead importé d'un fichier n'a PAS commenté : ces champs
                # restent vides plutôt que d'inventer un signal inexistant —
                # et `save_leads` n'écrase jamais un vrai commentaire par du vide.
                "comment_text": None,
                "commented_at": None,
                "reaction_count": 0,
            }
        )

    if not leads:
        raise LeadImportError(
            "Aucune URL de profil LinkedIn (linkedin.com/in/…) trouvée dans le fichier. "
            "Ajoute une colonne avec le lien du profil de chaque prospect, puis réessaie."
        )
    return {"leads": leads, "ignored": ignored, "rows": len(data_rows), "truncated": truncated}


# --------------------------------------------------------------------------- #
# Persistance (appelée par le job de fond)
# --------------------------------------------------------------------------- #

def persist_import(
    access_token: str,
    source: dict,
    leads: list[dict[str, Any]],
    ignored: int,
    rows: int,
    truncated: bool = False,
) -> dict[str, Any]:
    """Persiste les leads parsés et les note (ICP). Aucun débit de crédits.

    Même contrat de résultat que la recherche (`collect_and_persist_search`) :
    le polling frontend des `lead_collection_jobs` lit les mêmes champs.
    """
    from datetime import datetime, timezone

    from src import db
    from src.lead_finder import _score_leads_for_source

    counts = db.save_leads(access_token, source, leads)
    _score_leads_for_source(access_token, source, counts)
    db.update_lead_source(
        access_token,
        source["id"],
        {
            "comments_count": len(leads),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(
        f"[leads] import fichier {source['id']}: {len(leads)} profil(s) sur {rows} ligne(s), "
        f"{ignored} ignorée(s), leads {counts}",
        flush=True,
    )
    public_counts = {k: v for k, v in (counts or {}).items() if k != "ids_by_url"}
    return {
        "comments_count": len(leads),
        "profiles_count": len(leads),
        "ignored_rows": ignored,
        "total_rows": rows,
        "truncated": truncated,
        "leads": public_counts,
        "credits": None,
    }

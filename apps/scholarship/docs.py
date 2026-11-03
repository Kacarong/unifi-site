"""공고 원문(HTML 본문·첨부 HWP/HWPX/PDF/ZIP)에서 글자를 뽑고 신청 기간을 읽는다.

재단 공고는 본문이 이미지 한 장이고 날짜는 첨부 공고문에만 있는 경우가 많다.
사람이 파일을 내려받아 열어 봐야 알던 것을 여기서 대신 한다.

- text_of(data, name)  : 파일 바이트 → 글자 (HWP5·HWPX·PDF·ZIP 안의 그것들)
- find_period(text, posted) : 글자 → (시작일, 마감일). 연도가 빠진 날짜는 게시일로 채운다.
"""
from __future__ import annotations

import datetime as dt
import html
import io
import re
import struct
import zipfile
import zlib

MAX_FILE_BYTES = 20 * 1024 * 1024  # 공고문은 보통 1MB 안쪽. 큰 건 이미지 묶음이라 읽어도 소용없다.


# ---------------------------------------------------------------------------
# 파일 → 글자
# ---------------------------------------------------------------------------
def kind_of(data: bytes, name: str = "") -> str:
    head = data[:8]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "hwp"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile:
            return ""
        if any(n.startswith("Contents/section") for n in names):
            return "hwpx"
        return "zip"
    low = name.lower()
    if low.endswith((".htm", ".html")) or head.lstrip().startswith(b"<"):
        return "html"
    return ""


def _pdf_text(data: bytes) -> str:
    import pymupdf  # PyMuPDF — 요약정리본 기능 때문에 이미 기본 의존성이다

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        # sort=True: 표 안 글자가 칸마다 흩어져 나오는 PDF 가 많아 위→아래, 왼→오른 순으로 다시 늘어놓는다
        return "\n".join(page.get_text(sort=True) for page in doc)


def _hwp_records(buf: bytes):
    pos = 0
    while pos + 4 <= len(buf):
        (header,) = struct.unpack_from("<I", buf, pos)
        pos += 4
        tag, size = header & 0x3FF, header >> 20
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", buf, pos)
            pos += 4
        yield tag, buf[pos:pos + size]
        pos += size


_HWPTAG_PARA_TEXT = 67
# 문단 글자 안의 제어 문자. 이 번호들은 뒤에 7글자(14바이트)를 더 차지한다.
_HWP_WIDE_CTRL = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


def _hwp_para(raw: bytes) -> str:
    out = []
    i = 0
    n = len(raw) // 2
    while i < n:
        (ch,) = struct.unpack_from("<H", raw, i * 2)
        if ch < 32:
            if ch in _HWP_WIDE_CTRL:
                i += 8
                continue
            if ch in (10, 13):
                out.append("\n")
            i += 1
            continue
        out.append(chr(ch))
        i += 1
    return "".join(out)


def _hwp_text(data: bytes) -> str:
    """HWP5(한글 97 이후 바이너리). OLE 안의 BodyText/SectionN 레코드에서 문단 글자만 꺼낸다."""
    import olefile

    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & 0x2:
            return ""  # 암호가 걸린 문서
        compressed = bool(flags & 0x1)
        sections = sorted(
            (e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
            key=lambda e: int(e[1][7:] or 0),
        )
        parts = []
        for entry in sections:
            buf = ole.openstream(entry).read()
            if compressed:
                buf = zlib.decompress(buf, -15)
            for tag, body in _hwp_records(buf):
                if tag == _HWPTAG_PARA_TEXT:
                    parts.append(_hwp_para(body))
        return "\n".join(parts)
    finally:
        ole.close()


def _hwpx_text(zf: zipfile.ZipFile) -> str:
    parts = []
    for name in sorted(n for n in zf.namelist() if re.match(r"Contents/section\d+\.xml$", n)):
        xml = zf.read(name).decode("utf-8", "replace")
        xml = re.sub(r"</hp:p>", "\n", xml)
        parts.append(html.unescape(re.sub(r"<[^>]+>", "", xml)))
    return "\n".join(parts)


def html_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d|td|th)>", "\n", page)
    page = html.unescape(re.sub(r"<[^>]+>", " ", page))
    return re.sub(r"[ \t\xa0]+", " ", page)


def text_of(data: bytes, name: str = "", _depth: int = 0) -> str:
    """읽을 수 없는 형식(이미지 등)이면 빈 글자."""
    if not data or len(data) > MAX_FILE_BYTES:
        return ""
    kind = kind_of(data, name)
    try:
        if kind == "pdf":
            return _pdf_text(data)
        if kind == "hwp":
            return _hwp_text(data)
        if kind == "html":
            return html_text(data.decode("utf-8", "replace"))
        if kind in ("hwpx", "zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if kind == "hwpx":
                    return _hwpx_text(zf)
                if _depth:
                    return ""
                out = []
                # 공고문을 먼저 — 신청서 양식에도 날짜 칸이 있어서 헷갈린다
                names = sorted(zf.namelist(), key=lambda n: (not re.search(r"공고|요강|안내", _zipname(n)), n))
                for n in names[:10]:
                    info = zf.getinfo(n)
                    if info.is_dir() or info.file_size > MAX_FILE_BYTES:
                        continue
                    if re.search(r"\.(pdf|hwp|hwpx)$", n, re.I):
                        out.append(text_of(zf.read(n), n, _depth + 1))
                return "\n".join(out)
    except Exception:  # noqa: BLE001 - 깨진 파일 하나 때문에 전체가 멈추면 안 된다
        return ""
    return ""


def _zipname(n: str) -> str:
    """ZIP 안의 한글 파일 이름은 CP949 인데 zipfile 이 CP437 로 읽는다."""
    try:
        return n.encode("cp437").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return n


# ---------------------------------------------------------------------------
# 글자 → 신청 기간
# ---------------------------------------------------------------------------
# 신청 기간을 말하는 낱말. 이 낱말 뒤 가까이에 있는 날짜를 읽는다.
_LABEL = re.compile(
    r"(?:접수|모집|신청|지원|제출|원서)\s*(?:기간|기한|일정|일시|마감)"
    r"|(?:온라인|서류|인터넷)\s*(?:접수|신청|제출)|(?:신청|접수)\s*방법"
    r"|접\s*수|신\s*청\s*기\s*간"
)
_NOT_PERIOD = re.compile(r"선발\s*(?:기간|일정)|결과\s*발표|발표|면접|수여|지급|활동\s*기간|사업\s*기간|교육\s*기간")

# 2026. 10. 19.(월) / 2026-10-19 / 2026년 10월 19일 / 10. 19.(월) / 10월 19일 / 10/19
_DATE = re.compile(
    r"(?:(?P<y>20\d\d|\d\d)\s*(?:[.\-/]|년)\s*)?"
    r"(?P<m>1[0-2]|0?[1-9])\s*(?:[.\-/]|월)\s*(?P<d>3[01]|[12]\d|0?[1-9])(?!\d)\s*(?:일|\.)?"
    r"(?:\s*\(?\s*[월화수목금토일]\s*\(?\s*\)?)?"  # (월) — PDF 에선 '일월(   )' 처럼 흩어지기도 한다
    r"(?:\s*(?:\d{1,2}\s*[:시]\s*\d{0,2}\s*분?|오[전후]\s*\d{1,2}\s*시))?"
)
_RANGE_SEP = re.compile(r"^\s*(?:~|∼|〜|-|–|부터|까지\s*~)\s*")
_UNTIL = re.compile(r"^\s*(?:까지|限|마감)")


def _mk(y: int | None, m: int, d: int, ref: dt.date) -> dt.date | None:
    if y is not None and y < 100:
        y += 2000
    try:
        return dt.date(y or ref.year, m, d)
    except ValueError:
        return None


def _dates_after(text: str, start: int, limit: int = 160):
    """start 이후 limit 글자 안의 날짜들 — (date-match, 끝 위치)."""
    window = text[start:start + limit]
    for m in _DATE.finditer(window):
        yield m, start + m.end()


def find_period(text: str, posted: dt.date | None = None) -> tuple[dt.date | None, dt.date | None]:
    """신청 기간을 찾는다. 못 찾으면 (None, None), 마감일만 있으면 (None, 마감일).

    posted 는 연도가 빠진 날짜를 채우고, 연도 오타('2025.1.2~1.18' 을 2026년 1월에 올림)를
    바로잡는 데 쓴다 — 게시일보다 반년 넘게 앞선 기간은 연도를 하나 올린다.
    """
    if not text:
        return None, None
    ref = posted or dt.date.today()

    def _fix(d: dt.date, y: int | None, r: dt.date) -> dt.date:
        # 게시일을 모르면 연도 오타를 고칠 기준이 없다. 적힌 연도를 그대로 믿는다
        # (오늘을 기준으로 고치면 작년 공고가 올해 공고로 둔갑한다).
        if posted is None and y is not None:
            return d
        return _fix_year(d, y, r)
    best: tuple[dt.date | None, dt.date | None] | None = None
    for lab in _LABEL.finditer(text):
        # '선발 일정' 표 안의 '서류 접수' 처럼 라벨 바로 앞뒤에 다른 일정 낱말이 있으면 건너뛰지 않는다.
        # 다만 라벨 자체가 '결과 발표' 등이면 건너뛴다.
        line_start = text.rfind("\n", 0, lab.start()) + 1
        if _NOT_PERIOD.search(text[line_start:lab.start()]):
            continue
        found = list(_dates_after(text, lab.end()))
        if not found:
            continue
        m1, end1 = found[0]
        y1 = int(m1["y"]) if m1["y"] else None
        d1 = _mk(y1, int(m1["m"]), int(m1["d"]), ref)
        if not d1:
            continue
        rest = text[end1:end1 + 12]
        d2 = None
        if _RANGE_SEP.match(rest) and len(found) > 1:
            m2, _ = found[1]
            y2 = int(m2["y"]) if m2["y"] else None
            d2 = _mk(y2 or d1.year, int(m2["m"]), int(m2["d"]), ref)
            if d2 and d2 < d1 and not m2["y"]:
                d2 = _mk(d1.year + 1, int(m2["m"]), int(m2["d"]), ref)  # 12/20 ~ 1/10
        elif (
            _UNTIL.match(rest)
            or re.search(r"[~\-]\s*$", text[lab.end():m1.start() + lab.end()])  # '기한 : ~2026.1.15'
            or re.search(r"기한|마감", lab.group())  # '접수기한 2026.10.11'
        ):
            if not best or best[0] is None:
                best = (_start_before(text, lab.start(), _fix(d1, y1, ref), ref, _fix), _fix(d1, y1, ref))
            continue
        if d2:
            if not y1:
                d1, d2 = _fix(d1, None, ref), _fix(d2, None, ref)
                if d2 < d1:
                    d2 = d2.replace(year=d2.year + 1)
            else:
                d1, d2 = _fix(d1, y1, ref), _fix(d2, y1, ref)
            if 0 <= (d2 - d1).days <= 200:
                return d1, d2
    return best or (None, None)


def _start_before(text: str, pos: int, end: dt.date, ref: dt.date, fix) -> dt.date | None:
    """마감일만 라벨 뒤에 있을 때, 표의 같은 행에서 라벨 앞에 놓인 시작일.
    PDF 표는 '2026년 1월 2일(금) … 지원서 접수 - 1월 13일(화) 마감' 처럼 읽힌다."""
    found = list(_DATE.finditer(text[max(0, pos - 80):pos]))
    if not found:
        return None
    m = found[-1]
    y = int(m["y"]) if m["y"] else None
    d = _mk(y, int(m["m"]), int(m["d"]), ref)
    if d:
        d = fix(d, y, ref)
    if d and 0 < (end - d).days <= 120:
        return d
    return None


def _fix_year(d: dt.date, y: int | None, ref: dt.date) -> dt.date:
    """게시일 기준으로 말이 안 되는 연도를 고친다.
    - 연도 없음: 게시일보다 두 달 넘게 앞서면 다음 해다(12월 게시 '1/9 마감').
    - 연도 오타: 게시일보다 반년 넘게 앞서면 한 해 올린다(2026년 1월 게시 '2025.1.2').
    """
    limit = 60 if y is None else 180
    while (ref - d).days > limit:
        try:
            d = d.replace(year=d.year + 1)
        except ValueError:
            d = d.replace(year=d.year + 1, day=28)
    return d

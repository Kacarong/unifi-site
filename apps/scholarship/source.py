"""장학금 원본 데이터 — 공공데이터포털 '한국장학재단_학자금지원정보(대학생)'.

https://www.data.go.kr/data/15028252/fileData.do

한국장학재단이 정부·지자체·공공기관·민간 재단·대학의 장학금 공고를 모아
매달 CSV 로 올린다. 키나 로그인 없이 받을 수 있다. 다만 받는 길이 두 단계다.

  1. selectFileDataDownload.do 에 데이터셋 번호를 주면 이번 달 파일 번호
     (atchFileId)와 수정일이 나온다. 파일 번호는 갱신될 때마다 바뀐다.
  2. 그 파일 번호로 fileDownload.do 를 부르면 CSV(CP949)가 온다.

1단계는 가벼워서 자주 불러도 된다. 파일 번호가 그대로면 2단계를 건너뛴다.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
from typing import Any

DATASET_PK = "15028252"
DATASET_DETAIL_PK = "uddi:146a2f2a-3571-4768-9113-8dd47d67338b"
PAGE_URL = f"https://www.data.go.kr/data/{DATASET_PK}/fileData.do"
_META_URL = "https://www.data.go.kr/tcs/dss/selectFileDataDownload.do"
_FILE_URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do"
_UA = {"User-Agent": "Mozilla/5.0 (unifi-site scholarship)"}


class SourceError(RuntimeError):
    pass


def fetch_meta(timeout: float = 30) -> dict[str, str]:
    """이번 달 파일 번호와 수정일. 바뀌었을 때만 CSV 를 다시 받으면 된다."""
    body = urllib.parse.urlencode(
        {
            "publicDataPk": DATASET_PK,
            "publicDataDetailPk": DATASET_DETAIL_PK,
            "atchFileId": "",
            "fileDetailSn": "1",
            "publicDataTyCode": "PR0051",
        }
    ).encode()
    req = urllib.request.Request(_META_URL, data=body, headers=_UA, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 네트워크·JSON 오류를 한 종류로 알린다
        raise SourceError(f"공공데이터포털 응답을 읽지 못했습니다: {exc}") from exc
    if not data.get("status") or not data.get("atchFileId"):
        raise SourceError(f"공공데이터포털이 파일 정보를 주지 않았습니다: {str(data.get('error') or '')[:200]}")
    info = data.get("dataSetFileDetailInfo") or {}
    return {
        "file_id": str(data["atchFileId"]),
        "file_sn": str(data.get("fileDetailSn") or "1"),
        "name": str(info.get("dataNm") or ""),
        "updated": str(info.get("updtDt") or "")[:19],
    }


def fetch_csv(meta: dict[str, str], timeout: float = 120) -> bytes:
    qs = urllib.parse.urlencode({"atchFileId": meta["file_id"], "fileDetailSn": meta["file_sn"]})
    req = urllib.request.Request(f"{_FILE_URL}?{qs}", headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except Exception as exc:  # noqa: BLE001
        raise SourceError(f"장학금 CSV 를 받지 못했습니다: {exc}") from exc
    if len(raw) < 1000:
        raise SourceError("장학금 CSV 가 비어 있습니다")
    return raw


# ---------------------------------------------------------------------------
# 파싱
#
# 대학구분·학년구분·학과구분은 여러 값이 구분자 없이 붙어서 온다
# ("대학2학기대학3학기…대학신입생"). 아래 어휘로 잘라 목록으로 바꾼다.
# 실제 파일 1,925행 전부가 이 어휘로 남김없이 잘리는 것을 확인했다.
# ---------------------------------------------------------------------------
SCHOOL_VOCAB = [
    "4년제(5~6년제포함)", "전문대(2~3년제)", "일반대학원", "전문대학원", "기술대학",
    "원격대학", "학점은행제 대학", "해외대학", "특정대학", "제한없음", "해당없음",
]
GRADE_VOCAB = (
    ["대학신입생"] + [f"대학{i}학기" for i in range(2, 8)]
    + ["대학8학기이상", "석사신입생(1학기)", "석사2학기이상", "박사과정", "연령제한", "제한없음", "해당없음"]
)
FIELD_VOCAB = [
    "공학계열", "교육계열", "사회계열", "예체능계열", "의약계열", "인문계열", "자연계열",
    "특정학과", "제한없음", "해당없음",
]


def _splitter(vocab: list[str]):
    pat = re.compile("|".join(re.escape(v) for v in sorted(vocab, key=len, reverse=True)))
    return lambda text: pat.findall(text or "")


_split_school = _splitter(SCHOOL_VOCAB)
_split_grade = _splitter(GRADE_VOCAB)
_split_field = _splitter(FIELD_VOCAB)

# CSV 열 이름 → 우리 이름
_TEXT_COLUMNS = {
    "성적기준 상세내용": "grade_req",
    "소득기준 상세내용": "income",
    "지원내역 상세내용": "support",
    "특정자격 상세내용": "special",
    "지역거주여부 상세내용": "region",
    "선발방법 상세내용": "selection",
    "선발인원 상세내용": "quota",
    "자격제한 상세내용": "restriction",
    "추천필요여부 상세내용": "recommend",
    "제출서류 상세내용": "documents",
}


def _clean(text: str) -> str:
    """원문은 항목마다 '○' 를 붙여 한 줄로 이어 놓았다. 줄을 나눠 읽기 좋게."""
    text = (text or "").strip()
    text = re.sub(r"\s*(?=[○※])", "\n", text).strip()
    return text


def _url(text: str) -> str:
    text = (text or "").strip()
    if not text or text == "해당없음":
        return ""
    if not re.match(r"^https?://", text):
        text = "http://" + text
    return text


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(p.strip() for p in parts).encode("utf-8")).hexdigest()[:12]


def decode(raw: bytes) -> str:
    for enc in ("cp949", "utf-8-sig"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise SourceError("CSV 인코딩을 알 수 없습니다")


def parse(raw: bytes) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(io.StringIO(decode(raw))))
    if not rows or "상품명" not in rows[0]:
        raise SourceError("CSV 형식이 바뀌었습니다 (상품명 열이 없음)")

    items: dict[str, dict[str, Any]] = {}
    for row in rows:
        org = (row.get("운영기관명") or "").strip()
        name = (row.get("상품명") or "").strip()
        start = (row.get("모집시작일") or "").strip()[:10]
        end = (row.get("모집종료일") or "").strip()[:10]
        if not (org and name):
            continue
        item: dict[str, Any] = {
            # 행 번호는 달마다 바뀌므로 쓰지 않는다. 같은 장학금의 같은 회차면 같은 id.
            "id": _key(org, name, start),
            # 회차가 달라도 같은 장학금이면 같은 series — 관심 표시는 이 단위로 한다.
            "series": _key(org, name),
            "org": org,
            "name": name,
            "org_type": (row.get("운영기관구분") or "").strip(),
            "product": (row.get("상품구분") or "").strip(),
            "category": (row.get("학자금유형구분") or "").strip(),
            "schools": _split_school(row.get("대학구분", "")),
            "grades": _split_grade(row.get("학년구분", "")),
            "fields": _split_field(row.get("학과구분", "")),
            "url": _url(row.get("홈페이지 주소", "")),
            "start": start,
            "end": end,
        }
        for col, key in _TEXT_COLUMNS.items():
            item[key] = _clean(row.get(col, ""))
        items[item["id"]] = item
    return list(items.values())

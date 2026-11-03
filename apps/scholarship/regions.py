"""지역 이름 — 장학금 거주 조건을 시·도 / 시·군·구 두 단계로 읽기 위한 어휘.

낱말 하나만 맞으면 통과시키면 '부산, 해운대구' 인 사람에게 '부산 수영구 거주'
장학금이 보인다. 그래서 공고가 시·군·구까지 적었으면 시·군·구로, 시·도까지만
적었으면 시·도로 맞춘다. 같은 이름의 구(동구·중구 …)가 여러 시에 있으므로
공고에 시·도가 같이 적혀 있으면 시·도도 맞아야 한다.
"""
from __future__ import annotations

import re

# 표준 키 → 공고에 나오는 표기들
SIDO_ALIASES: dict[str, list[str]] = {
    "서울": ["서울"],
    "부산": ["부산"],
    "대구": ["대구"],
    "인천": ["인천"],
    "광주": ["광주광역시", "광주"],
    "대전": ["대전"],
    "울산": ["울산"],
    "세종": ["세종"],
    "경기": ["경기"],
    "강원": ["강원"],
    "충북": ["충청북도", "충북"],
    "충남": ["충청남도", "충남"],
    "전북": ["전라북도", "전북"],
    "전남": ["전라남도", "전남"],
    "경북": ["경상북도", "경북"],
    "경남": ["경상남도", "경남"],
    "제주": ["제주"],
}

# 시·도별 시·군·구 (자치구·시·군). 인천은 2026년 개편 전후 이름을 둘 다 둔다.
SIGUNGU: dict[str, list[str]] = {
    "서울": "종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 "
            "마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구".split(),
    "부산": "중구 서구 동구 영도구 부산진구 동래구 남구 북구 해운대구 사하구 금정구 강서구 연제구 수영구 "
            "사상구 기장군".split(),
    "대구": "중구 동구 서구 남구 북구 수성구 달서구 달성군 군위군".split(),
    "인천": "중구 동구 미추홀구 연수구 남동구 부평구 계양구 서구 강화군 옹진군 제물포구 영종구 서해구 검단구".split(),
    "광주": "동구 서구 남구 북구 광산구".split(),
    "대전": "동구 중구 서구 유성구 대덕구".split(),
    "울산": "중구 남구 동구 북구 울주군".split(),
    "경기": "수원시 성남시 의정부시 안양시 부천시 광명시 평택시 동두천시 안산시 고양시 과천시 구리시 남양주시 "
            "오산시 시흥시 군포시 의왕시 하남시 용인시 파주시 이천시 안성시 김포시 화성시 광주시 양주시 포천시 "
            "여주시 연천군 가평군 양평군".split(),
    "강원": "춘천시 원주시 강릉시 동해시 태백시 속초시 삼척시 홍천군 횡성군 영월군 평창군 정선군 철원군 화천군 "
            "양구군 인제군 고성군 양양군".split(),
    "충북": "청주시 충주시 제천시 보은군 옥천군 영동군 증평군 진천군 괴산군 음성군 단양군".split(),
    "충남": "천안시 공주시 보령시 아산시 서산시 논산시 계룡시 당진시 금산군 부여군 서천군 청양군 홍성군 예산군 "
            "태안군".split(),
    "전북": "전주시 군산시 익산시 정읍시 남원시 김제시 완주군 진안군 무주군 장수군 임실군 순창군 고창군 부안군".split(),
    "전남": "목포시 여수시 순천시 나주시 광양시 담양군 곡성군 구례군 고흥군 보성군 화순군 장흥군 강진군 해남군 "
            "영암군 무안군 함평군 영광군 장성군 완도군 진도군 신안군".split(),
    "경북": "포항시 경주시 김천시 안동시 구미시 영주시 영천시 상주시 문경시 경산시 의성군 청송군 영양군 영덕군 "
            "청도군 고령군 성주군 칠곡군 예천군 봉화군 울진군 울릉군".split(),
    "경남": "창원시 진주시 통영시 사천시 김해시 밀양시 거제시 양산시 의령군 함안군 창녕군 고성군 남해군 하동군 "
            "산청군 함양군 거창군 합천군".split(),
    "제주": "제주시 서귀포시".split(),
}

_SIDO_OF: dict[str, set[str]] = {}
for _key, _names in SIGUNGU.items():
    for _name in _names:
        _SIDO_OF.setdefault(_name, set()).add(_key)

_ALIAS_TO_SIDO = {alias: key for key, aliases in SIDO_ALIASES.items() for alias in aliases}
_ALL_SIGUNGU = sorted({name for names in SIGUNGU.values() for name in names}, key=len, reverse=True)

# 긴 이름부터 시도해야 '강남구' 안의 '남구', '광주광역시' 와 '광주' 를 헷갈리지 않는다.
_SIDO_RE = re.compile("|".join(re.escape(a) for a in sorted(_ALIAS_TO_SIDO, key=len, reverse=True)))
_SIGUNGU_RE = re.compile("|".join(re.escape(n) for n in _ALL_SIGUNGU))


def find(text: str) -> tuple[set[str], set[str]]:
    """글에 나온 (시·도 키, 시·군·구 이름)."""
    text = text or ""
    sido = {_ALIAS_TO_SIDO[m] for m in _SIDO_RE.findall(text)}
    sigungu = set(_SIGUNGU_RE.findall(text))
    # '광주시' 는 경기도다. 그 안의 '광주' 를 광역시로 세면 안 된다.
    if "광주시" in sigungu and "광주광역시" not in text:
        sido.discard("광주")
        sido.add("경기")
    return sido, sigungu


def sido_of(sigungu: set[str]) -> set[str]:
    """한 시·도에만 있는 이름이면 그 시·도. '서대문구' → 서울, '동구' 는 여러 곳이라 모름."""
    out: set[str] = set()
    for name in sigungu:
        owners = _SIDO_OF.get(name, set())
        if len(owners) == 1:
            out |= owners
    return out


def classify_word(word: str) -> tuple[str, str]:
    """사용자가 적은 낱말 하나 → ('sido', 키) / ('sigungu', 이름) / ('free', 낱말)."""
    word = word.strip()
    if word in _ALIAS_TO_SIDO:  # '광주' 는 경기 광주시보다 광주광역시로 본다
        return "sido", _ALIAS_TO_SIDO[word]
    if word in _ALL_SIGUNGU:
        return "sigungu", word
    for suffix in ("구", "군", "시"):
        if len(word) >= 2 and word + suffix in _ALL_SIGUNGU:
            return "sigungu", word + suffix
    m = _SIDO_RE.match(word)  # 부산광역시, 경기도, 강원특별자치도 …
    if m:
        return "sido", _ALIAS_TO_SIDO[m.group()]
    return "free", word

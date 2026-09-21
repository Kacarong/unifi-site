"""지오글로브 — Cesium 기반 지리 학습 지구본 (프론트엔드 전용).

백엔드가 없고 `web/` 의 Vite 프로젝트를 빌드해서 정적으로 서빙한다.
원본 레포: https://github.com/Kacarong/geoglobe
"""
from server.registry import AppSpec, BuildSpec

SPEC = AppSpec(
    id="geoglobe",
    name="지오글로브",
    tagline="지구본으로 지리 익히고 퀴즈로 복습",
    accent="#22c9a0",
    icon="🌍",
    description="Cesium 지구본 위에서 국가·도시·강·해협 레이어를 켜고 끄며 지리를 익히고, 퀴즈로 복습합니다.",
    tags=["지도", "학습", "프론트엔드"],
    static_dir="web/dist",
    build=BuildSpec(cwd="web", install="npm install", command="npm run build"),
)

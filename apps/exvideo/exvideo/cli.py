import argparse
import os
import sys

from . import __version__


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="exvideo",
        description="강의 영상 → 전사 + 슬라이드 텍스트 + 슬라이드/그림 이미지 → 붙여넣기용 프롬프트 묶음",
    )
    p.add_argument("input", help="영상 파일 경로 또는 구글드라이브/URL 링크")
    p.add_argument("-o", "--out", default="output", help="결과 저장 폴더 (기본: output)")
    p.add_argument("--model", default="large-v3", help="Whisper 모델 크기 (tiny/base/small/medium/large-v3)")
    p.add_argument("--lang", default="ko", help="음성 언어 코드 (기본: ko)")
    p.add_argument("--sample-interval", type=float, default=1.0, help="슬라이드 검사 간격(초)")
    p.add_argument("--diff-threshold", type=float, default=8.0, help="슬라이드 전환 감지 민감도(클수록 둔감)")
    p.add_argument("--no-ocr", action="store_true", help="슬라이드 OCR 생략")
    p.add_argument("--no-figures", action="store_true", help="그림 크롭 생략")
    p.add_argument("--skip-transcribe", action="store_true", help="음성 전사 생략(슬라이드만)")
    p.add_argument("--cpu", action="store_true", help="GPU 대신 CPU 강제")
    p.add_argument("--version", action="version", version=f"ex-video {__version__}")
    args = p.parse_args(argv)

    from .pipeline import run_pipeline
    res = run_pipeline(
        args.input, os.path.abspath(args.out),
        model=args.model, lang=args.lang,
        sample_interval=args.sample_interval, diff_threshold=args.diff_threshold,
        do_transcribe=not args.skip_transcribe, do_ocr=not args.no_ocr,
        do_figures=not args.no_figures, cpu=args.cpu,
    )
    print("\n완료!")
    print(f"  - 프롬프트 묶음: {res['bundle']}")
    print(f"  - 슬라이드 이미지: {res['slides_dir']}")
    print(f"  - 그림 이미지:   {res['figures_dir']}")
    print("이 bundle.md 내용을 Gemini/Claude에 붙여넣고, 필요하면 슬라이드/그림 이미지를 함께 첨부하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

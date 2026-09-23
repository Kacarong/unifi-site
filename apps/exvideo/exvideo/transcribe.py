"""faster-whisper로 영상의 음성을 타임스탬프 포함 전사한다 (로컬, GPU 자동)."""
import ctypes
import gc
import glob
import os
import sys

# ctranslate2(faster-whisper의 연산 엔진)가 GPU 를 쓰려면 CUDA 12 판 cuBLAS·cuDNN 이
# 필요하다. pip 로 깔면 site-packages/nvidia/ 아래에 들어가는데, 이 경로는 동적 링커가
# 모르는 자리라 LD_LIBRARY_PATH 를 미리 걸어 주지 않으면 못 찾는다.
# 그런데 LD_LIBRARY_PATH 는 프로세스가 뜰 때 읽히므로 안에서 고쳐 봐야 소용없다.
# 그래서 직접 열어 프로세스에 올려 둔다. 그러면 ctranslate2 가 이어서 찾아 쓴다.
_CUDA_LIBS = ("cublas/lib/libcublas.so.12", "cudnn/lib/libcudnn.so.9")


def preload_cuda_libs() -> list[str]:
    """pip 로 깔린 CUDA 라이브러리를 미리 올린다. 올린 것들의 경로를 돌려준다."""
    loaded = []
    for site in sys.path:
        root = os.path.join(site, "nvidia")
        if not os.path.isdir(root):
            continue
        for rel in _CUDA_LIBS:
            for path in glob.glob(os.path.join(root, rel)):
                try:
                    ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                    loaded.append(path)
                except OSError:
                    pass            # 못 열면 시스템에 깔린 것을 쓰게 둔다
        if loaded:
            break
    return loaded


def pick_device() -> tuple[str, str]:
    """쓸 장치를 고른다. 반환: (device, 그렇게 고른 이유).

    예전에는 torch 로 CUDA 를 확인했다. 그런데 faster-whisper 는 torch 를 쓰지 않는다.
    그래서 torch 가 안 깔린 환경에서는 GPU 가 멀쩡히 있어도 조용히 CPU 로 떨어졌다.
    실제로 그렇게 돌고 있었다. 실제로 연산을 맡을 ctranslate2 에게 직접 물어본다.
    """
    try:
        import ctranslate2
    except ImportError:
        return "cpu", "ctranslate2 가 없어 CPU 로 돕니다"
    try:
        n = ctranslate2.get_cuda_device_count()
    except Exception as exc:
        return "cpu", f"GPU 확인에 실패해 CPU 로 돕니다 ({exc})"
    if n < 1:
        return "cpu", "쓸 수 있는 GPU 가 없어 CPU 로 돕니다"
    return "cuda", f"GPU {n}개를 씁니다"


def _plan(device: str, compute_type: str) -> list[tuple[str, str]]:
    """시도할 (장치, 연산정밀도) 차례.

    이 GPU 는 다른 서비스와 같이 쓴다(음성인식·음성합성이 늘 3GB 가까이 물고 있다).
    그래서 large-v3 를 float16 으로 올리면 VRAM 이 모자라 터진다 — 실제로 터졌다.
    터지고 마는 대신 한 단계씩 낮춰 간다. int8_float16 은 절반 남짓만 쓰고 품질 차이는
    거의 없다. 그것마저 안 되면 CPU 로 간다. 느려도 끝은 난다.
    """
    steps = [(device, compute_type)]
    if device == "cuda" and compute_type != "int8_float16":
        steps.append(("cuda", "int8_float16"))
    if device == "cuda":
        steps.append(("cpu", "int8"))
    return steps


def _is_oom(exc: Exception) -> bool:
    return "out of memory" in str(exc).lower()


def transcribe(video_path: str, model_size: str = "large-v3", language: str = "ko",
               device: str = "auto", compute_type: str = "auto"):
    """반환: [{start, end, text}]"""
    from faster_whisper import WhisperModel  # 지연 임포트

    if device == "auto":
        device, why = pick_device()
        print(f"[전사] {why}")
    if device == "cuda":
        preload_cuda_libs()
    if compute_type == "auto":
        # GPU 기본값이 float16 이 아닌 이유: 이 GPU(8GB)는 다른 서비스와 나눠 쓴다.
        # large-v3 를 float16 으로 올리면 VRAM 이 모자라고, int8_float16 은 그 절반만
        # 쓰면서 실측 품질이 오히려 나았다('미분'을 medium/small 은 '미군'으로 적었다).
        compute_type = "int8_float16" if device == "cuda" else "int8"

    steps = _plan(device, compute_type)
    for i, (dev, ct) in enumerate(steps):
        print(f"[전사] Whisper 모델 로딩 (size={model_size}, device={dev}, compute={ct}) ...")
        model = None
        try:
            model = WhisperModel(model_size, device=dev, compute_type=ct)
            segments, _ = model.transcribe(video_path, language=language, vad_filter=True)
            out = []
            for seg in segments:   # 여기서 실제로 계산이 돈다 — OOM 도 여기서 난다
                out.append({"start": float(seg.start), "end": float(seg.end),
                            "text": seg.text.strip()})
                print(f"  [{int(seg.start)//60:02d}:{int(seg.start)%60:02d}] {seg.text.strip()[:60]}")
            return out
        except RuntimeError as exc:
            if not _is_oom(exc) or i == len(steps) - 1:
                raise
            nxt = steps[i + 1]
            print(f"[전사] GPU 메모리가 모자랍니다 — {nxt[0]}/{nxt[1]} 로 다시 시도합니다")
        finally:
            # 실패한 모델을 붙들고 있으면 다음 시도도 똑같이 메모리가 모자란다.
            # 실제로 이것 때문에 GPU 로 충분히 되는 조합까지 건너뛰고 CPU 로 떨어졌다.
            del model
            gc.collect()
    raise RuntimeError("전사에 실패했습니다.")   # 여기까지 오지 않는다

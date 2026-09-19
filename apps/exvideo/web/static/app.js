const API = "/api/exvideo";
const $ = (id) => document.getElementById(id);
let pollTimer = null;
let currentJob = null;

async function startJob() {
  const source = $("source").value.trim();
  if (!source) { alert("영상 주소를 입력하세요."); return; }
  const body = {
    source,
    transcribe: $("transcribe").checked,
    ocr: $("ocr").checked,
    figures: $("figures").checked,
    model: $("model").value,
  };
  $("startBtn").disabled = true;
  const res = await fetch(`${API}/jobs`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) { alert("작업 시작 실패"); $("startBtn").disabled = false; return; }
  const { job_id } = await res.json();
  currentJob = job_id;
  $("progressCard").classList.remove("hidden");
  $("doneBtns").classList.add("hidden");
  $("previewCard").classList.add("hidden");
  poll();
}

async function poll() {
  if (!currentJob) return;
  const res = await fetch(`${API}/jobs/${currentJob}`);
  const j = await res.json();
  $("barFill").style.width = (j.progress || 0) + "%";
  $("statusText").textContent = `상태: ${statusKo(j.status)} (${j.progress || 0}%)`;
  $("log").textContent = (j.messages || []).join("\n");
  $("log").scrollTop = $("log").scrollHeight;

  if (j.status === "done") {
    $("statusText").textContent = `완료! 슬라이드 ${j.result?.n_slides ?? "?"}개`;
    $("doneBtns").classList.remove("hidden");
    loadPreview();
    return;
  }
  if (j.status === "error") {
    $("statusText").textContent = "오류: " + (j.error || "알 수 없음");
    $("startBtn").disabled = false;
    return;
  }
  pollTimer = setTimeout(poll, 1500);
}

function statusKo(s) {
  return { queued: "대기 중", running: "처리 중", done: "완료", error: "오류" }[s] || s;
}

async function loadPreview() {
  try {
    const res = await fetch(`${API}/jobs/${currentJob}/bundle`);
    const txt = await res.text();
    $("preview").textContent = txt;
    $("previewCard").classList.remove("hidden");
  } catch (e) { /* ignore */ }
}

$("startBtn").addEventListener("click", startJob);
$("dlZip").addEventListener("click", () => { window.location = `${API}/jobs/${currentJob}/download`; });
$("dlBundle").addEventListener("click", () => { window.open(`${API}/jobs/${currentJob}/bundle`, "_blank"); });
$("againBtn").addEventListener("click", () => {
  if (pollTimer) clearTimeout(pollTimer);
  currentJob = null;
  $("startBtn").disabled = false;
  $("progressCard").classList.add("hidden");
  $("previewCard").classList.add("hidden");
});

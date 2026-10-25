# ruff: noqa: E501 - embedded HTML/CSS/JS reads better unwrapped
"""The dashboard HTML, laid out for a 7-inch 800x480 display (also fine on a phone)."""

PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>live drawing plotter</title>
<style>
  :root { --bg:#111; --panel:#1c1c1c; --fg:#eee; --muted:#888; --accent:#f5a623; --ok:#3cb371; --warn:#d9534f; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; background: var(--bg); color: var(--fg); font-family: system-ui, sans-serif; }
  body { display: grid; grid-template-rows: 1fr auto; height: 100vh; padding: 8px; gap: 8px; }
  main { display: grid; grid-template-columns: 62fr 38fr; gap: 8px; min-height: 0; }
  .side { display: grid; grid-template-rows: 1fr 1fr; gap: 8px; min-height: 0; }
  figure { background: var(--panel); border-radius: 8px; position: relative; min-height: 0; overflow: hidden; display: flex; align-items: center; justify-content: center; }
  figure img { max-width: 100%; max-height: 100%; object-fit: contain; }
  figcaption { position: absolute; top: 6px; left: 8px; font-size: 13px; color: var(--muted); background: rgba(0,0,0,.5); padding: 2px 6px; border-radius: 4px; }
  footer { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: center; }
  #status { font-size: 15px; line-height: 1.5; }
  #phase { font-weight: 700; font-size: 20px; }
  #phase.drawing { color: var(--ok); } #phase.paused, #phase.ready { color: var(--accent); } #phase.idle { color: var(--muted); }
  .buttons { display: flex; gap: 8px; }
  button { min-width: 120px; min-height: 60px; font-size: 20px; border: 0; border-radius: 10px; color: #111; background: var(--fg); cursor: pointer; }
  button:disabled { opacity: .35; cursor: default; }
  #pause { background: var(--accent); } #resume { background: var(--ok); } #newpaper { background: var(--warn); color: #fff; }
  #offline { display: none; color: var(--warn); }
  #problem { display: none; color: var(--warn); font-weight: 700; }
  #problem small { display: block; font-weight: 400; color: var(--muted); font-size: 12px; }
  @media (max-width: 600px) { main { grid-template-columns: 1fr; } .side { grid-template-rows: none; grid-template-columns: 1fr 1fr; } }
</style>
</head>
<body>
<main>
  <figure><img id="camera" src="/camera.mjpg" alt="camera"><figcaption>カメラ</figcaption></figure>
  <div class="side">
    <figure><img id="paper" src="/paper.jpg" alt="paper"><figcaption>紙の状態</figcaption></figure>
    <figure><img id="edges" src="/edges.jpg" alt="edges"><figcaption>抽出した輪郭</figcaption></figure>
  </div>
</main>
<footer>
  <div id="status">
    <div id="phase">起動中</div>
    <div id="detail">-</div>
    <div id="problem"><span id="problem-text"></span><small id="problem-detail"></small></div>
    <div id="offline">本体と通信できません</div>
  </div>
  <div class="buttons">
    <button id="pause" onclick="control('pause')">一時停止</button>
    <button id="resume" onclick="control('resume')">再開</button>
    <button id="newpaper" onclick="newPaper()">新しい紙</button>
  </div>
</footer>
<script>
const PHASES = { starting: "起動中", waiting_camera: "カメラ待ち", waiting_plotter: "AxiDraw 接続待ち", drawing: "描画中", idle: "待機中（新しい変化なし）", paused: "一時停止中", ready: "開始待ち（紙とペンをセットして「開始」）" };
const PROBLEMS = {
  camera: "カメラが見つかりません。USB 接続を確認してください（自動で再試行中）",
  plotter: "AxiDraw に接続できません。電源と USB を確認してください（自動で再試行中）",
  plotter_stopped: "AxiDraw が停止しました。キャリッジを手で左上の角に戻してから「開始」を押してください",
  cycles: "映像の処理に失敗しています。カメラの映像を確認してください",
};
let lastUpdated = -1;
let streamHealthy = false;
function restartCameraStream() { document.getElementById("camera").src = "/camera.mjpg?" + Date.now(); }
async function refresh() {
  try {
    const s = await (await fetch("/status.json", { cache: "no-store" })).json();
    document.getElementById("offline").style.display = "none";
    const problem = document.getElementById("problem");
    problem.style.display = s.problem ? "block" : "none";
    if (s.problem) {
      document.getElementById("problem-text").textContent = PROBLEMS[s.problem.kind] || s.problem.kind;
      document.getElementById("problem-detail").textContent = s.problem.detail || "";
    }
    const healthy = !(s.problem && s.problem.kind === "camera");
    if (healthy && !streamHealthy) restartCameraStream();  // the MJPEG stream dies with the camera or the process
    streamHealthy = healthy;
    const phase = document.getElementById("phase");
    phase.textContent = PHASES[s.phase] || s.phase;
    phase.className = s.phase;
    document.getElementById("detail").textContent =
      `サイクル ${s.cycle} / 候補 ${s.candidates} 本 / 被覆率 ${(s.coverage * 100).toFixed(1)}% / 累計 ${(s.drawn_mm / 1000).toFixed(2)} m` +
      (s.dry_run ? " / ドライラン" : "") + (s.saturated ? " / 紙がほぼ埋まっています" : "");
    document.getElementById("pause").disabled = s.paused;
    const resume = document.getElementById("resume");
    resume.disabled = !s.paused;
    resume.textContent = (s.cycle === 0 && s.drawn_mm === 0) ? "開始" : "再開";
    if (s.updated !== lastUpdated) {
      lastUpdated = s.updated;
      document.getElementById("paper").src = "/paper.jpg?" + s.updated;
      document.getElementById("edges").src = "/edges.jpg?" + s.updated;
    }
  } catch (e) {
    document.getElementById("offline").style.display = "block";
    streamHealthy = false;
  }
}
async function control(action) {
  try {
    await fetch("/control", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
  } finally { refresh(); }
}
function newPaper() {
  if (confirm("描画済みの記憶を消して、新しい紙として始めます。\\n紙をセットしてから「開始」を押してください。よろしいですか？")) control("new_paper");
}
refresh();
setInterval(refresh, 1000);
</script>
</body>
</html>
"""

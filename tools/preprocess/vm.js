// VM mode of the editor (editor.py --vm, see editor.py VM): hides what needs the raw asset packs (elements marked
// data-pc) and adds the "게임에 반영" bar — the game reads data/ only at startup, so a save is applied by
// POST /api/apply (server check → DB copy → systemctl restart), whose log is polled from GET /api/apply/log.
// Included by every editor page; does nothing when the editor runs on the PC.
(async () => {
  let st;
  try { st = await (await fetch("/api/vm")).json(); } catch { return; }
  if (!st.vm) return;
  document.body.classList.add("vm");
  const css = document.createElement("style");
  css.textContent = `
    .vm [data-pc] { display: none !important; }
    #vmbar { flex-basis: 100%; border: 1px solid #c9a84c; border-radius: 4px; padding: 4px 8px; font-size: 12px; background: #1a1a22; margin: 4px 0; }
    #vmbar b { color: #c9a84c; } #vmbar .dim { opacity: .7; } #vmbar button { margin: 0 6px; padding: 1px 8px; }
    #vmlog { max-height: 180px; overflow: auto; margin: 4px 0 0; font: 11px ui-monospace, monospace; white-space: pre-wrap; }
    #vmlog:empty { display: none; }`;
  document.head.appendChild(css);
  // the slice tab is useless without the sheets: open on the items tab
  const items = document.getElementById("tabItems");
  if (items && document.body.dataset.tab === "furn") items.click();

  const bar = document.createElement("div");
  bar.id = "vmbar";
  bar.innerHTML = `<b>VM 모드</b> <span class="dim">여기서 저장한 건 게임이 다시 시작해야 읽어요 →</span>`
    + `<button id="vmApply" title="서버 검증 → DB 복사(server/backups/) → systemctl restart interior. 접속자가 2~3초 끊겨요">게임에 반영</button>`
    + `<span class="dim">슬라이스 자르기·빌드·캐릭터·고양이 빌드는 원본 그림이 있는 PC에서만. 여기서 고친 건 PC에서 <code>./deploy/pull.sh</code>로 가져가 커밋해요.</span>`
    + `<pre id="vmlog"></pre>`;
  const log = document.getElementById("log");
  if (log) log.parentNode.insertBefore(bar, log);
  else (document.getElementById("bottom") || document.body).appendChild(bar);
  const out = document.getElementById("vmlog"), btn = document.getElementById("vmApply");

  const poll = async () => {
    let from = 0;
    out.textContent = "";
    for (;;) {
      const j = await (await fetch(`/api/apply/log?from=${from}`)).json();
      if (j.lines.length) { out.textContent += (out.textContent ? "\n" : "") + j.lines.join("\n"); out.scrollTop = out.scrollHeight; }
      from = j.next;
      if (j.done) return j.ok;
      await new Promise((r) => setTimeout(r, 700));
    }
  };
  btn.onclick = async () => {
    if (!confirm("저장한 내용으로 게임 서버를 다시 시작할까요?\n접속 중인 사람은 2~3초 끊겨요. 방 seed를 바꿨으면 그 방 seed가 새로 심겨요 (DB 복사본이 남아요).")) return;
    btn.disabled = true;
    try {
      const r = await (await fetch("/api/apply", { method: "POST" })).json();
      if (!r.ok) { out.textContent = "✖ " + r.error; return; }
      await poll();
    } catch (e) { out.textContent += "\n✖ " + e.message; }
    finally { btn.disabled = false; }
  };
  // a run started from another tab (or before a reload) is still shown
  if (st.apply && !st.apply.idle) {
    out.textContent = st.apply.lines.join("\n");
    if (!st.apply.done) { btn.disabled = true; poll().finally(() => { btn.disabled = false; }); }
  }
})();

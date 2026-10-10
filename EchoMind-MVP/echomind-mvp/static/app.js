/* ============================================================
   EchoMind 前端逻辑（纯原生 JS，无任何外部依赖）
   流程：首页 → 情绪输入 → 场景选择 → 目标状态 → 生成方案
        → 播放页 → 反馈页 → 本次记录 → 历史记录
   所有播放行为（播放/暂停/跳过/播完）都会打点上报后端。
   ============================================================ */
(function () {
  "use strict";

  /* ---------- 常量 ---------- */
  var EMOTIONS = ["紧张", "烦躁", "低落", "疲惫", "难以专注", "平静"];
  var SCENES = ["考试前", "演出前", "学习", "写论文", "睡前", "通勤", "独处", "其他"];
  var GOALS = [
    { name: "平静下来", desc: "从紧绷慢慢松下来，回到平稳" },
    { name: "放松", desc: "放下手头的事，好好松弛一下" },
    { name: "专注", desc: "收束注意力，进入心流" },
    { name: "恢复能量", desc: "温和地把电量充回来" },
    { name: "暂时不想思考", desc: "放空大脑，什么都不想" },
  ];
  // 目标 -> 播放页"当前目标"文案（从情绪 → ?）
  var GOAL_WORD = { "平静下来": "平稳", "放松": "放松", "专注": "专注", "恢复能量": "有能量", "暂时不想思考": "放空" };

  /* ---------- 用户标识（localStorage 生成 UUID，长期有效） ---------- */
  function getUserId() {
    var id = localStorage.getItem("echomind_user_id");
    if (!id) {
      id = "u_" + Math.random().toString(36).slice(2) +
        Date.now().toString(36) + Math.random().toString(36).slice(2);
      localStorage.setItem("echomind_user_id", id);
    }
    return id;
  }

  /* ---------- 会话状态 ---------- */
  var state = {
    emotion: null, intensity: 5,
    scene: null, goal: null,
    sessionId: null, plan: null, explanation: "",
    stageIdx: 0, sessionStart: 0, playedTitles: [],
  };

  /* ---------- 屏幕切换 ---------- */
  function show(id) {
    document.querySelectorAll(".screen").forEach(function (el) {
      el.classList.toggle("active", el.id === id);
    });
    window.scrollTo(0, 0);
  }
  document.querySelectorAll("[data-back]").forEach(function (btn) {
    btn.addEventListener("click", function () { show(btn.dataset.back); });
  });

  function $(id) { return document.getElementById(id); }

  /* ---------- 选项渲染 ---------- */
  function renderChips(containerId, items, onPick) {
    var box = $(containerId);
    box.innerHTML = "";
    items.forEach(function (item) {
      var b = document.createElement("button");
      b.className = "chip";
      b.textContent = item;
      b.addEventListener("click", function () {
        box.querySelectorAll(".chip").forEach(function (c) { c.classList.remove("selected"); });
        b.classList.add("selected");
        onPick(item);
      });
      box.appendChild(b);
    });
  }

  renderChips("emotion-chips", EMOTIONS, function (v) {
    state.emotion = v;
    $("emotion-label").textContent = v;
    $("feedback-emotion").textContent = v;
    $("feedback-emotion-2").textContent = v;
    $("btn-emotion-next").disabled = false;
  });
  renderChips("scene-chips", SCENES, function (v) {
    state.scene = v;
    $("btn-scene-next").disabled = false;
  });
  (function renderGoals() {
    var box = $("goal-cards");
    GOALS.forEach(function (g) {
      var d = document.createElement("div");
      d.className = "card";
      d.innerHTML = '<div class="card-title">' + g.name + '</div>' +
        '<div class="card-sub">' + g.desc + "</div>";
      d.addEventListener("click", function () {
        box.querySelectorAll(".card").forEach(function (c) { c.classList.remove("selected"); });
        d.classList.add("selected");
        state.goal = g.name;
        $("btn-goal-next").disabled = false;
      });
      box.appendChild(d);
    });
  })();

  /* ---------- 强度滑杆 ---------- */
  $("intensity").addEventListener("input", function (e) {
    state.intensity = parseInt(e.target.value, 10);
    $("intensity-val").textContent = state.intensity;
  });
  $("intensity-after").addEventListener("input", function (e) {
    $("after-val").textContent = e.target.value;
    $("fb-after-val").textContent = e.target.value;
  });

  /* ---------- 首页 ---------- */
  $("btn-start").addEventListener("click", function () { show("s-emotion"); });
  $("btn-checkin").addEventListener("click", function () { show("s-emotion"); });
  $("btn-history").addEventListener("click", function () { loadHistory(); show("s-history"); });
  $("btn-emotion-next").addEventListener("click", function () { show("s-scene"); });
  $("btn-scene-next").addEventListener("click", function () { show("s-goal"); });

  /* ---------- 生成方案 ---------- */
  var STAGE_NUM = { "释放": "01", "稳定": "02", "放松": "03", "专注": "04", "能量": "05" };
  $("btn-goal-next").addEventListener("click", function () {
    var btn = $("btn-goal-next");
    btn.disabled = true;
    btn.textContent = "生成中…";
    fetch("/api/session/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: getUserId(),
        emotion: state.emotion,
        intensity_before: state.intensity,
        scene: state.scene,
        goal: state.goal,
      }),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        btn.disabled = false;
        btn.textContent = "生成我的音乐方案";
        if (!res.ok) { alert("生成失败：" + (res.j.error || "未知错误")); return; }
        state.sessionId = res.j.session_id;
        state.plan = res.j.plan;
        state.explanation = res.j.plan.explanation;
        state.stageIdx = 0;
        state.sessionStart = Date.now();
        state.playedTitles = [];
        renderPlan();
        show("s-plan");
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = "生成我的音乐方案";
        alert("网络异常，请检查服务是否启动");
      });
  });

  function renderPlan() {
    $("plan-emotion").textContent = state.emotion + " · " + state.intensity + "/10";
    $("plan-scene").textContent = state.scene;
    $("plan-goal").textContent = state.goal;
    $("plan-why").textContent = state.explanation;
    var path = $("plan-path");
    path.innerHTML = "";
    state.plan.stages.forEach(function (s, i) {
      var d = document.createElement("div");
      d.className = "path-step";
      d.innerHTML = '<div class="num">' + (STAGE_NUM[s.stage] || ("0" + (i + 1))) + "</div>" +
        '<div class="info"><div class="t">' + s.stage + " · " + s.track.title + "</div>" +
        '<div class="s">' + s.reason + "</div></div>";
      path.appendChild(d);
      if (i < state.plan.stages.length - 1) {
        var a = document.createElement("div");
        a.className = "path-arrow";
        a.textContent = "↓";
        path.appendChild(a);
      }
    });
  }

  /* ---------- 播放器 ---------- */
  var audio = new Audio();
  audio.preload = "auto";
  var currentTrackId = null;
  var endedLogged = false;

  function logEvent(action) {
    if (!state.sessionId || !currentTrackId) return;
    fetch("/api/session/" + state.sessionId + "/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        track_id: currentTrackId,
        action: action,
        position_sec: Math.round(audio.currentTime || 0),
      }),
    }).catch(function () { /* 打点失败不打断体验 */ });
  }

  function fmt(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    return Math.floor(sec / 60) + ":" + ("0" + (sec % 60)).slice(-2);
  }

  function loadStage(i, autoplay) {
    var stages = state.plan.stages;
    if (i < 0) i = 0;
    if (i >= stages.length) { goFeedback(); return; }
    state.stageIdx = i;
    var s = stages[i];
    var t = s.track;
    currentTrackId = t.id;
    endedLogged = false;
    $("player-stage").textContent = "当前调节阶段：" + s.stage;
    $("player-goal").textContent = "当前目标：从" + state.emotion + " → " + (GOAL_WORD[state.goal] || "平稳");
    $("player-cover").src = t.cover_url;
    $("player-title").textContent = t.title;
    $("player-tag").textContent = s.stage + " · 约" + t.bpm + "BPM · 刺激度" + t.stimulation + " · " + t.timbre;
    audio.src = t.file_url;
    $("progress-fill").style.width = "0%";
    $("time-cur").textContent = "0:00";
    $("time-total").textContent = "加载中…";
    if (state.playedTitles.indexOf(t.title) === -1) state.playedTitles.push(t.title);
    if (autoplay) {
      audio.play().catch(function () { /* 需用户手势，等待点击播放 */ });
    }
  }

  function setPlayIcon() {
    $("btn-play").textContent = audio.paused ? "▶" : "⏸";
  }

  $("btn-plan-go").addEventListener("click", function () {
    show("s-player");
    loadStage(0, true);
    startBreath();
  });

  $("btn-play").addEventListener("click", function () {
    if (audio.paused) { audio.play().catch(function () {}); }
    else { audio.pause(); }
  });
  audio.addEventListener("play", function () { setPlayIcon(); logEvent("play"); });
  audio.addEventListener("pause", function () {
    setPlayIcon();
    if (!audio.ended) logEvent("pause");
  });
  audio.addEventListener("loadedmetadata", function () {
    $("time-total").textContent = fmt(audio.duration);
  });
  audio.addEventListener("timeupdate", function () {
    if (audio.duration) {
      $("progress-fill").style.width = (audio.currentTime / audio.duration * 100) + "%";
      $("time-cur").textContent = fmt(audio.currentTime);
    }
  });
  audio.addEventListener("ended", function () {
    if (endedLogged) return;
    endedLogged = true;
    logEvent("complete");
    // 自动进入下一阶段；播完最后一段则进入反馈页
    setTimeout(function () { loadStage(state.stageIdx + 1, true); }, 800);
  });
  $("progress").addEventListener("click", function (e) {
    var r = this.getBoundingClientRect();
    var ratio = (e.clientX - r.left) / r.width;
    if (audio.duration) audio.currentTime = ratio * audio.duration;
  });
  $("btn-next").addEventListener("click", function () {
    logEvent("skip");
    loadStage(state.stageIdx + 1, true);
  });
  $("btn-prev-stage").addEventListener("click", function () {
    logEvent("skip");
    loadStage(state.stageIdx - 1, true);
  });
  $("btn-player-back").addEventListener("click", function () {
    audio.pause();
    show("s-plan");
  });
  $("btn-player-finish").addEventListener("click", function () {
    audio.pause();
    goFeedback();
  });

  /* ---------- 呼吸圆环文字（吸气 4s → 呼气 6s，与 CSS 动画 10s 周期同步） ---------- */
  var breathTimer = null;
  function startBreath() {
    if (breathTimer) return;
    var label = $("breath-label");
    function cycle() {
      label.textContent = "吸气";
      setTimeout(function () { label.textContent = "呼气"; }, 4000);
    }
    cycle();
    breathTimer = setInterval(cycle, 10000);
  }

  /* ---------- 反馈 ---------- */
  function goFeedback() {
    $("fb-before").textContent = state.intensity;
    $("intensity-after").value = state.intensity;
    $("after-val").textContent = state.intensity;
    $("fb-after-val").textContent = state.intensity;
    show("s-feedback");
  }

  $("btn-feedback-submit").addEventListener("click", function () {
    var after = parseInt($("intensity-after").value, 10);
    var durationSec = Math.round((Date.now() - state.sessionStart) / 1000);
    var btn = $("btn-feedback-submit");
    btn.disabled = true;
    btn.textContent = "提交中…";
    fetch("/api/session/" + state.sessionId + "/finish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intensity_after: after, duration_sec: durationSec }),
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        btn.disabled = false;
        btn.textContent = "生成本次记录";
        renderRecord(j, durationSec);
        show("s-record");
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = "生成本次记录";
        alert("提交失败，请重试");
      });
  });

  function renderRecord(j, durationSec) {
    var before = j.intensity_before, after = j.intensity_after;
    var delta = before - after;
    $("record-delta").textContent = before + " → " + after;
    var emoWord = state.emotion;
    var sub;
    if (delta > 0) sub = "你的主观" + emoWord + "程度较使用前降低了 " + delta + " 级。";
    else if (delta < 0) sub = "你的主观" + emoWord + "程度较使用前升高了 " + (-delta) + " 级，辛苦了，抱抱你。";
    else sub = "你的主观" + emoWord + "程度与使用前持平，陪伴本身也是一种调节。";
    $("record-sub").textContent = sub;
    $("record-emotion").textContent = emoWord + " " + before + "/10";
    $("record-scene").textContent = state.scene;
    $("record-goal").textContent = state.goal;
    var m = Math.floor(durationSec / 60), s = durationSec % 60;
    $("record-duration").textContent = (m > 0 ? m + "分" : "") + s + "秒";
    $("record-tracks").textContent = state.playedTitles.join("、") || "—";
  }

  $("btn-record-history").addEventListener("click", function () { loadHistory(); show("s-history"); });
  $("btn-record-home").addEventListener("click", function () { show("s-home"); });
  $("btn-history-new").addEventListener("click", function () { show("s-emotion"); });

  /* ---------- 历史记录 ---------- */
  function loadHistory() {
    fetch("/api/history?user_id=" + encodeURIComponent(getUserId()))
      .then(function (r) { return r.json(); })
      .then(function (j) { renderHistory(j.sessions || []); })
      .catch(function () { renderHistory([]); });
  }

  function fmtDate(iso) {
    // "2026-09-28T08:10:22" -> "09.28"
    var d = new Date(iso.replace(" ", "T"));
    if (isNaN(d)) return iso.slice(5, 10).replace("-", ".");
    return ("0" + (d.getMonth() + 1)).slice(-2) + "." + ("0" + d.getDate()).slice(-2);
  }

  function renderHistory(sessions) {
    var list = $("history-list");
    list.innerHTML = "";
    var done = sessions.filter(function (s) { return s.completed; });
    $("history-empty").style.display = done.length ? "none" : "block";
    $("history-chart-wrap").style.display = done.length ? "block" : "none";

    done.forEach(function (s) {
      var d = document.createElement("div");
      d.className = "hist-card";
      var delta = (s.intensity_before != null && s.intensity_after != null)
        ? "主观强度 " + s.intensity_before + " → " + s.intensity_after : "未完成反馈";
      var mins = s.duration_sec != null ? Math.round(s.duration_sec / 60) + "min" : "—";
      d.innerHTML = '<div class="date">' + fmtDate(s.created_at) + " · " + s.scene + " · " + s.goal + "</div>" +
        '<div class="main">' + s.emotion + "</div>" +
        '<div class="delta">' + delta + "</div>" +
        '<div class="sub">使用时长 ' + mins + " · " +
        s.plan.stages.map(function (st) { return st.track.title; }).join(" → ") + "</div>";
      list.appendChild(d);
    });

    // 折线图：横轴=使用次数，纵轴=强度 1-10；两条线：使用前 / 使用后
    var svg = $("history-chart");
    svg.innerHTML = "";
    if (!done.length) return;
    var W = 400, H = 150, P = 18;
    var n = done.length;
    function x(i) { return n === 1 ? W / 2 : P + (W - 2 * P) * (i / (n - 1)); }
    function y(v) { return H - P - ((v - 1) / 9) * (H - 2 * P); }
    var NS = "http://www.w3.org/2000/svg";
    // 网格线（强度 1/5/10）
    [1, 5, 10].forEach(function (v) {
      var ln = document.createElementNS(NS, "line");
      ln.setAttribute("x1", P); ln.setAttribute("x2", W - P);
      ln.setAttribute("y1", y(v)); ln.setAttribute("y2", y(v));
      ln.setAttribute("stroke", "#d9d4f2"); ln.setAttribute("stroke-width", "1");
      svg.appendChild(ln);
    });
    function polyline(key, color) {
      var pts = done.map(function (s, i) { return x(i) + "," + y(s[key]); }).join(" ");
      var pl = document.createElementNS(NS, "polyline");
      pl.setAttribute("points", pts);
      pl.setAttribute("fill", "none");
      pl.setAttribute("stroke", color);
      pl.setAttribute("stroke-width", "3");
      pl.setAttribute("stroke-linecap", "round");
      pl.setAttribute("stroke-linejoin", "round");
      svg.appendChild(pl);
      done.forEach(function (s, i) {
        var c = document.createElementNS(NS, "circle");
        c.setAttribute("cx", x(i)); c.setAttribute("cy", y(s[key]));
        c.setAttribute("r", "4.5"); c.setAttribute("fill", color);
        svg.appendChild(c);
      });
    }
    polyline("intensity_before", "#b3a8ec");
    polyline("intensity_after", "#544bb8");
  }
})();

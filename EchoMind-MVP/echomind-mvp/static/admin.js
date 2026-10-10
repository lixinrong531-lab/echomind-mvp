/* ============================================================
   EchoMind 管理后台逻辑（纯原生 JS，无外部依赖）
   鉴权：管理密钥经 X-Admin-Key 请求头发送，存于 sessionStorage。
   ============================================================ */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  var adminKey = sessionStorage.getItem("echomind_admin_key") || "";

  function api(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers["X-Admin-Key"] = adminKey;
    return fetch(path, opts).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
    });
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;")
      .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* ---------- 登录 ---------- */
  function tryLogin() {
    adminKey = $("admin-key").value.trim();
    api("/api/admin/stats").then(function (res) {
      if (res.status === 401 || !res.ok) {
        $("login-err").style.display = "block";
        return;
      }
      sessionStorage.setItem("echomind_admin_key", adminKey);
      $("login-box").style.display = "none";
      $("admin-main").style.display = "block";
      renderStats(res.j);
      loadTracks();
      loadSessions();
    }).catch(function () { $("login-err").style.display = "block"; });
  }
  $("btn-login").addEventListener("click", tryLogin);
  $("admin-key").addEventListener("keydown", function (e) { if (e.key === "Enter") tryLogin(); });
  if (adminKey) { $("admin-key").value = adminKey; tryLogin(); }

  /* ---------- 数据总览 ---------- */
  function renderStats(s) {
    var cards = [
      ["用户数", s.users], ["使用次数", s.sessions],
      ["完成反馈", s.completed_sessions],
      ["使用前均分", s.avg_before == null ? "—" : s.avg_before],
      ["使用后均分", s.avg_after == null ? "—" : s.avg_after],
    ];
    $("stat-cards").innerHTML = cards.map(function (c) {
      return '<div class="stat-card"><div class="n">' + c[1] + '</div><div class="l">' + c[0] + "</div></div>";
    }).join("");
    renderBars("emotion-bars", s.emotion_dist);
    renderBars("scene-bars", s.scene_dist);

    $("scene-table").querySelector("tbody").innerHTML =
      (s.scene_feedback || []).map(function (r) {
        return "<tr><td>" + esc(r.scene) + "</td><td>" + r.count + "</td><td>" +
          r.avg_before + "</td><td>" + r.avg_after + "</td><td>" + r.avg_delta + "</td></tr>";
      }).join("") || '<tr><td colspan="5">暂无完成反馈的数据</td></tr>';

    $("track-stat-table").querySelector("tbody").innerHTML =
      (s.track_plays || []).map(function (r) {
        return "<tr><td>" + esc(r.title) + "</td><td>" + esc(r.stage) + "</td><td>" +
          (r.plays || 0) + "</td><td>" + (r.completes || 0) + "</td><td>" + (r.skips || 0) + "</td></tr>";
      }).join("");
  }

  // 纯 CSS/div 条形图
  function renderBars(elId, dist) {
    var entries = Object.entries(dist || {}).sort(function (a, b) { return b[1] - a[1]; });
    var max = entries.length ? entries[0][1] : 1;
    $(elId).innerHTML = entries.map(function (e) {
      var w = Math.max(4, Math.round(e[1] / max * 100));
      return '<div class="bar-row"><span class="name">' + esc(e[0]) + '</span>' +
        '<span class="bar"><i style="width:' + w + '%"></i></span>' +
        '<span class="cnt">' + e[1] + "</span></div>";
    }).join("") || '<p class="hint">暂无数据</p>';
  }

  /* ---------- 曲目管理 ---------- */
  function loadTracks() {
    api("/api/admin/tracks").then(function (res) {
      if (!res.ok) return;
      var tb = $("track-table").querySelector("tbody");
      tb.innerHTML = "";
      res.j.tracks.forEach(function (t) {
        var tr = document.createElement("tr");
        tr.innerHTML = "<td>" + t.id + "</td><td>" + esc(t.title) + "</td><td>" + esc(t.stage) +
          "</td><td>" + (t.bpm || "—") + "</td><td>" + esc(t.stimulation || "") + "</td><td>" +
          t.scene_tags.map(function (s) { return '<span class="tag">' + esc(s) + "</span>"; }).join("") +
          "</td><td>" + (t.enabled ? "✓" : "✗") + "</td><td>" +
          '<button class="mini-btn" data-edit="' + t.id + '">编辑</button>' +
          '<button class="mini-btn" data-toggle="' + t.id + '">' + (t.enabled ? "停用" : "启用") + "</button>" +
          '<button class="mini-btn danger" data-del="' + t.id + '">删除</button></td>';
        tb.appendChild(tr);
      });
      tb.querySelectorAll("[data-edit]").forEach(function (b) {
        b.addEventListener("click", function () { editTrack(parseInt(b.dataset.edit, 10), res.j.tracks); });
      });
      tb.querySelectorAll("[data-toggle]").forEach(function (b) {
        b.addEventListener("click", function () {
          var id = parseInt(b.dataset.toggle, 10);
          var cur = res.j.tracks.find(function (t) { return t.id === id; });
          api("/api/admin/tracks/" + id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: !cur.enabled }),
          }).then(loadTracks);
        });
      });
      tb.querySelectorAll("[data-del]").forEach(function (b) {
        b.addEventListener("click", function () {
          if (!confirm("确定删除该曲目吗？")) return;
          api("/api/admin/tracks/" + b.dataset.del, { method: "DELETE" }).then(loadTracks);
        });
      });
    });
  }

  function trackFormJson(t) {
    // 简单 prompt 表单：标题 / 阶段 / BPM / 刺激度 / 场景标签（逗号分隔）
    var title = prompt("标题", t ? t.title : "");
    if (title === null) return null;
    var stage = prompt("推荐阶段（释放/稳定/放松/专注/能量）", t ? t.stage : "放松");
    if (stage === null) return null;
    var bpm = prompt("BPM（观感值）", t ? t.bpm : "60");
    if (bpm === null) return null;
    var stim = prompt("刺激程度（低/中低）", t ? t.stimulation : "低");
    if (stim === null) return null;
    var scenes = prompt("场景标签（逗号分隔，如：睡前,通用）",
      t ? t.scene_tags.join(",") : "通用");
    if (scenes === null) return null;
    var emotions = prompt("情绪标签（逗号分隔）",
      t ? t.emotion_tags.join(",") : "");
    if (emotions === null) return null;
    return {
      title: title.trim(),
      stage: stage.trim(),
      bpm: parseInt(bpm, 10) || null,
      stimulation: stim.trim(),
      scene_tags: scenes.split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean),
      emotion_tags: emotions.split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean),
    };
  }

  $("btn-track-add").addEventListener("click", function () {
    var data = trackFormJson(null);
    if (!data) return;
    data.file = ""; data.cover = "";  // 新增曲目可后续补充音频/封面路径
    api("/api/admin/tracks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }).then(function (res) {
      if (!res.ok) alert("添加失败：" + (res.j.error || ""));
      loadTracks();
    });
  });

  function editTrack(id, tracks) {
    var cur = tracks.find(function (t) { return t.id === id; });
    var data = trackFormJson(cur);
    if (!data) return;
    api("/api/admin/tracks/" + id, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }).then(function (res) {
      if (!res.ok) alert("保存失败：" + (res.j.error || ""));
      loadTracks();
    });
  }

  /* ---------- 会话明细 ---------- */
  function loadSessions() {
    api("/api/admin/sessions").then(function (res) {
      if (!res.ok) return;
      var tb = $("session-table").querySelector("tbody");
      tb.innerHTML = (res.j.sessions || []).map(function (s) {
        var fb = (s.intensity_before != null && s.intensity_after != null)
          ? s.intensity_before + "/" + s.intensity_after : s.intensity_before + "/—";
        var dur = s.duration_sec != null ? Math.round(s.duration_sec) + "s" : "—";
        return "<tr><td>" + esc(s.created_at) + "</td><td>" + esc(s.emotion) + "</td><td>" + fb +
          "</td><td>" + esc(s.scene) + "</td><td>" + esc(s.goal) + "</td><td>" + dur +
          "</td><td>" + esc(s.plan_titles.join(" → ")) + "</td><td>" + s.event_count + "</td></tr>";
      }).join("") || '<tr><td colspan="8">暂无会话</td></tr>';
    });
  }

  /* ---------- 导出 CSV ---------- */
  $("btn-export").addEventListener("click", function () {
    window.location.href = "/api/admin/export.csv?key=" + encodeURIComponent(adminKey);
  });
})();

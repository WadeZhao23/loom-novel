/*! Loom 图标基线 —— iconfont(Symbol/SVG sprite)格式的本地图标集
 * --------------------------------------------------------------------------
 * 这是一份「可直接用」的线性图标 sprite,31 个 symbol id 与 app.js 的 IC 表一一对应。
 * 离线、随包走,符合 Loom 本地优先。
 *
 * 想换成你自己在 iconfont.cn 挑的图标:
 *   项目页 → Symbol 标签 → 「下载至本地」拿到 iconfont.js → 覆盖本文件即可。
 *   只要 symbol id 同名(见 docs/design/iconfont.md 采购清单),app.js 零改动。
 *
 * 取色:每个 symbol 用 stroke="currentColor",所以图标颜色 = 文字色,明暗主题自动适配。
 * 单位:viewBox 0 0 24,线宽 1.8,圆头圆角。
 */
(function () {
  "use strict";

  // id -> path(可多段,用换行分隔仅为可读,渲染无关)
  var P = {
    "icon-book":
      "M4 5.5C4 5 4.5 4.5 6 4.5C9 4.5 11 5.5 12 6.5C13 5.5 15 4.5 18 4.5C19.5 4.5 20 5 20 5.5V18C20 18.5 19.5 19 18 19C15 19 13 19.5 12 20.5C11 19.5 9 19 6 19C4.5 19 4 18.5 4 18V5.5ZM12 6.5V20.5",
    "icon-key":
      "M12.5 12.5a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM11.3 9.7 20 1M17 4l2 2M15 6l2 2",
    "icon-sun":
      "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
    "icon-moon":
      "M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z",
    "icon-focus":
      "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM22 12h-3M5 12H2M12 5V2M12 22v-3",
    "icon-fullscreen-exit":
      "M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3M16 21v-3a2 2 0 0 1 2-2h3",
    "icon-doc":
      "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5ZM14 3v5h5M9 13h6M9 17h6",
    "icon-arrow-right":
      "M4 12h16M14 6l6 6-6 6",
    "icon-export":
      "M12 16V4M8 8l4-4 4 4M4 14v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4",
    "icon-save":
      "M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2ZM17 21v-8H7v8M7 3v5h7",
    "icon-brain":
      "M9.5 4A2.5 2.5 0 0 0 7 6.5 2.5 2.5 0 0 0 4.5 9 2.5 2.5 0 0 0 5 13.9 2.5 2.5 0 0 0 9.5 20 2 2 0 0 0 11 18.2V5.8A2 2 0 0 0 9.5 4ZM14.5 4A2.5 2.5 0 0 1 17 6.5 2.5 2.5 0 0 1 19.5 9 2.5 2.5 0 0 1 19 13.9 2.5 2.5 0 0 1 14.5 20 2 2 0 0 1 13 18.2V5.8A2 2 0 0 1 14.5 4Z",
    "icon-fingerprint":
      "M4.8 12a7.2 7.2 0 0 1 14.4 0M8 12a4 4 0 0 1 8 0v3M12 12v6M16 13a6 6 0 0 1-.8 5",
    "icon-magic":
      "M4 20 13 11M17 3l1 2.8 2.8 1L18 7.8 17 10.6 16 7.8 13.2 6.8 16 5.8ZM5.5 3.5l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4L3.5 6l1.4-.6Z",
    "icon-tool":
      "M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76Z",
    "icon-robot":
      "M12 2.5a1.3 1.3 0 1 0 0 2.6 1.3 1.3 0 0 0 0-2.6ZM12 5.1V8M6 8h12a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1ZM9.5 13h.01M14.5 13h.01M2 12v4M22 12v4M9.5 16h5",
    "icon-search":
      "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM21 21l-4.35-4.35",
    "icon-scissors":
      "M6.5 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM6.5 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM20 4 8.6 15.4M14.6 14.6 20 20M8.6 8.6 12.5 12.5",
    "icon-trend-up":
      "M22 7l-8.5 8.5-5-5L2 17M16 7h6v6",
    "icon-arrow-up":
      "M12 20V4M6 10l6-6 6 6",
    "icon-arrow-down":
      "M12 4v16M6 14l6 6 6-6",
    "icon-close":
      "M18 6 6 18M6 6l12 12",
    "icon-pin":
      "M12 17v5M9 10.8V4h6v6.8a2 2 0 0 0 .6 1.4l1.4 1.4v1.4H7v-1.4l1.4-1.4A2 2 0 0 0 9 10.8Z",
    "icon-edit":
      "M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z",
    "icon-check":
      "M20 6 9 17l-5-5",
    "icon-cross":
      "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM15 9l-6 6M9 9l6 6",
    "icon-refresh":
      "M20.5 12a8.5 8.5 0 1 1-2.5-6M20.5 4v5h-5",
    "icon-warning":
      "M12 3.5 2.3 20.5h19.4L12 3.5ZM12 10v4.5M12 18h.01",
    "icon-play":
      "M7 5l12 7-12 7V5Z",
    "icon-skip":
      "M5 5l11 7-11 7V5ZM20 5v14",
    "icon-chevron-right":
      "M9 6l6 6-6 6",
    "icon-arrow-left":
      "M19 12H5M11 6l-6 6 6 6",
    "icon-history":
      "M3.5 9a9 9 0 1 1-.3 5M3.5 4.5V9H8M12 8v4.5l3.5 2",
    "icon-plus":
      "M12 5v14M5 12h14",
    "icon-trash":
      "M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13M10 11v6M14 11v6"
  };

  var common =
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
    'stroke-linecap="round" stroke-linejoin="round"';

  var symbols = "";
  for (var id in P) {
    if (Object.prototype.hasOwnProperty.call(P, id)) {
      symbols +=
        '<symbol id="' + id + '" ' + common + '><path d="' + P[id] + '"/></symbol>';
    }
  }
  var svg =
    '<svg xmlns="http://www.w3.org/2000/svg" style="position:absolute;width:0;height:0;overflow:hidden" aria-hidden="true">' +
    symbols +
    "</svg>";

  function inject() {
    if (document.getElementById("__loom_iconfont__")) return;
    var div = document.createElement("div");
    div.id = "__loom_iconfont__";
    div.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
    div.setAttribute("aria-hidden", "true");
    div.innerHTML = svg;
    var b = document.body;
    if (b.firstChild) b.insertBefore(div, b.firstChild);
    else b.appendChild(div);
  }

  if (document.body) inject();
  else document.addEventListener("DOMContentLoaded", inject);
})();

#!/usr/bin/env python3
"""Mr.GUO 学习工作台 — 一个浏览器页面搞定所有学习流程"""

import os
import re
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request
import markdown

app = Flask(__name__)

ROOT = Path(__file__).resolve().parent.parent  # Mr.GUO/
LECTURES_DIR = ROOT / "docs" / "lectures"
PROMPTS_DIR = ROOT / "prompts"
TEMPLATES_DIR = ROOT / "templates"

# ── 讲次元数据 ──────────────────────────────────────────────
LECTURES = [
    {"id": "00", "title": "第零章 · 极简前置铺垫", "part": "前置", "file": "chapter0.md"},
    {"id": "01", "title": "CR-EI：瞎逛", "part": "第一篇 · 采样更聪明", "file": "01.md"},
    {"id": "02", "title": "Filter-GEI：集群空转", "part": "第一篇 · 采样更聪明", "file": "02.md"},
    {"id": "03", "title": "GSDE：126 维奇迹", "part": "第一篇 · 采样更聪明", "file": "03.md"},
    {"id": "04", "title": "DA-EGO：动态分解", "part": "第一篇 · 采样更聪明", "file": "04.md"},
    {"id": "05", "title": "EMFS/MSFO：后期假优", "part": "第一篇 · 采样更聪明", "file": "05.md"},
    {"id": "06", "title": "GMFoO：多潜空间", "part": "第二篇 · 换潜空间", "file": "06.md"},
    {"id": "07", "title": "SW-VAE/KT-ASO：迁移", "part": "第二篇 · 换潜空间", "file": "07.md"},
    {"id": "08", "title": "GTO：梯度反推", "part": "第二篇 · 换潜空间", "file": "08.md"},
    {"id": "09", "title": "VAE-NURBS 端壁", "part": "第二篇 · 换潜空间", "file": "09.md"},
    {"id": "10", "title": "TNO：神经算子", "part": "第三篇 · 场预测", "file": "10.md"},
    {"id": "11", "title": "SDNO：叠加原理", "part": "第三篇 · 场预测", "file": "11.md"},
    {"id": "12", "title": "P-ResUNet：相似原理", "part": "第三篇 · 场预测", "file": "12.md"},
    {"id": "13", "title": "SHAP：归因分析", "part": "第三篇 · 场预测", "file": "13.md"},
    {"id": "14", "title": "流固耦合数字孪生", "part": "第三篇 · 场预测", "file": "14.md"},
    {"id": "15", "title": "子午面全景预测", "part": "第三篇 · 场预测", "file": "15.md"},
    {"id": "16", "title": "端壁：三涡+气膜", "part": "第四篇 · 物理实验", "file": "16.md"},
    {"id": "17", "title": "NAE-Exp：风洞实验", "part": "第四篇 · 物理实验", "file": "17.md"},
    {"id": "18", "title": "FFD-Tip：叶尖", "part": "第四篇 · 物理实验", "file": "18.md"},
    {"id": "19", "title": "Slot-UQ：不确定性", "part": "第四篇 · 物理实验", "file": "19.md"},
    {"id": "20", "title": "复合冷却构型", "part": "第四篇 · 物理实验", "file": "20.md"},
]


def read_md(path: Path) -> str:
    """读取 Markdown 并转为 HTML"""
    if not path.exists():
        return "<p>文件不存在</p>"
    text = path.read_text("utf-8")
    # 简化图片路径：去掉 ./images/ 前缀中的相对路径
    text = text.replace("](./images/", "](/images/")
    text = text.replace("](../../../prompts/", "](/prompts/")
    text = text.replace("](../../../templates/", "](/templates/")
    html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "nl2br"],
    )
    return html


def get_prompt(lecture_id: str, kind: str) -> str:
    """读取某讲的专属 Prompt"""
    # kind: preview / recall / review
    prompt_file = PROMPTS_DIR / "per_lectures" / f"L{lecture_id}_{kind}.md"
    if not prompt_file.exists():
        # 回退到通用 Prompt
        fallback = {
            "preview": "00_before_each_lecture/preview_guide.md",
            "recall": "01_after_reading/active_recall.md",
            "review": "04_end_of_lecture/critical_review.md",
        }
        prompt_file = PROMPTS_DIR / fallback.get(kind, "")
    if prompt_file.exists():
        text = prompt_file.read_text("utf-8")
        # 提取 ``` ``` 之间的 Prompt 内容
        match = re.search(r"```(?:markdown|text)?\n(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text
    return "Prompt 文件不存在"


def get_task(lecture_id: str) -> str:
    """从讲义中提取动手任务"""
    lec = next((l for l in LECTURES if l["id"] == lecture_id), None)
    if not lec:
        return ""
    path = LECTURES_DIR / lec["file"]
    if not path.exists():
        return ""
    text = path.read_text("utf-8")
    # 提取 ### 动手任务 到 ### 沉淀清单 之间的内容
    match = re.search(r"### 动手任务\n(.*?)(?=### 沉淀清单|\Z)", text, re.DOTALL)
    if match:
        md_text = match.group(1).strip()
        return markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    return "<p>本讲暂无动手任务</p>"


def get_deposit(lecture_id: str) -> str:
    """从讲义中提取沉淀清单"""
    lec = next((l for l in LECTURES if l["id"] == lecture_id), None)
    if not lec:
        return ""
    path = LECTURES_DIR / lec["file"]
    if not path.exists():
        return ""
    text = path.read_text("utf-8")
    match = re.search(r"### 沉淀清单\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    if match:
        md_text = match.group(1).strip()
        return markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    return "<p>本讲暂无沉淀清单</p>"


# ── 路由 ────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, lectures=LECTURES)


@app.route("/api/lecture/<lid>")
def api_lecture(lid):
    lec = next((l for l in LECTURES if l["id"] == lid), None)
    if not lec:
        return jsonify({"error": "讲次不存在"}), 404
    path = LECTURES_DIR / lec["file"]
    # 如果文件在 docs/ 根目录
    if not path.exists():
        path = ROOT / "docs" / lec["file"]
    return jsonify({
        "id": lec["id"],
        "title": lec["title"],
        "part": lec["part"],
        "html": read_md(path),
        "task": get_task(lid),
        "deposit": get_deposit(lid),
    })


@app.route("/api/prompt/<lid>/<kind>")
def api_prompt(lid, kind):
    return jsonify({"text": get_prompt(lid, kind)})


@app.route("/images/<path:filename>")
def serve_image(filename):
    from flask import send_from_directory
    return send_from_directory(ROOT / "docs" / "images", filename)


@app.route("/prompts/<path:filename>")
def serve_prompt(filename):
    from flask import send_from_directory
    return send_from_directory(PROMPTS_DIR, filename)


@app.route("/templates/<path:filename>")
def serve_template(filename):
    from flask import send_from_directory
    return send_from_directory(TEMPLATES_DIR, filename)


@app.route("/api/learning_os")
def api_learning_os():
    path = ROOT / "docs" / "learning_os.md"
    return jsonify({"html": read_md(path)})


# ── HTML 模板 ────────────────────────────────────────────────
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mr.GUO 学习工作台</title>
<style>
  :root {
    --bg: #0f1117;
    --bg2: #161b22;
    --bg3: #1c2333;
    --fg: #c9d1d9;
    --fg2: #8b949e;
    --accent: #58a6ff;
    --accent2: #3fb950;
    --accent3: #d2a8ff;
    --border: #30363d;
    --radius: 8px;
    --sidebar-w: 280px;
    --toolbar-w: 340px;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--fg); display:flex; height:100vh; overflow:hidden; }
  
  /* ── 侧边栏 ── */
  #sidebar {
    width: var(--sidebar-w); min-width: var(--sidebar-w);
    background: var(--bg2); border-right: 1px solid var(--border);
    display: flex; flex-direction: column; overflow: hidden;
  }
  #sidebar-header {
    padding: 16px; border-bottom: 1px solid var(--border);
    font-size: 15px; font-weight: 600; color: var(--accent);
    display: flex; align-items: center; gap: 8px;
  }
  #sidebar-header span { font-size: 20px; }
  #nav { flex:1; overflow-y:auto; padding: 8px 0; }
  .nav-part {
    padding: 6px 16px; font-size: 11px; font-weight: 600;
    color: var(--fg2); text-transform: uppercase; letter-spacing: 0.5px;
    margin-top: 8px;
  }
  .nav-item {
    padding: 8px 16px; cursor: pointer; font-size: 13px;
    display: flex; align-items: center; gap: 8px;
    transition: background 0.15s;
  }
  .nav-item:hover { background: var(--bg3); }
  .nav-item.active { background: var(--bg3); color: var(--accent); border-left: 3px solid var(--accent); }
  .nav-item .nav-id {
    font-size: 11px; color: var(--fg2); width: 20px; text-align: right;
    font-family: monospace;
  }
  .nav-item .nav-status {
    margin-left: auto; font-size: 10px;
    width: 16px; height: 16px; border-radius: 50%;
    border: 1.5px solid var(--border); display: flex;
    align-items: center; justify-content: center;
    cursor: pointer; transition: all 0.2s;
  }
  .nav-item .nav-status.done { background: var(--accent2); border-color: var(--accent2); color: #fff; }
  .nav-item .nav-status:hover { border-color: var(--accent); }

  /* ── 主内容区 ── */
  #main { flex:1; display:flex; flex-direction:column; overflow:hidden; }
  #topbar {
    height: 48px; background: var(--bg2); border-bottom: 1px solid var(--border);
    display: flex; align-items: center; padding: 0 20px; gap: 12px;
  }
  #topbar-title { font-size: 14px; font-weight: 600; }
  #topbar-part { font-size: 12px; color: var(--fg2); }
  .topbar-btn {
    margin-left: auto; padding: 4px 12px; font-size: 12px;
    background: var(--bg3); border: 1px solid var(--border);
    border-radius: var(--radius); color: var(--fg); cursor: pointer;
    transition: all 0.15s;
  }
  .topbar-btn:hover { border-color: var(--accent); color: var(--accent); }
  #content-area { flex:1; display:flex; overflow:hidden; }
  
  /* ── 讲义内容 ── */
  #lecture-content {
    flex: 1; overflow-y: auto; padding: 24px 32px;
    max-width: 800px;
  }
  #lecture-content h1, #lecture-content h2, #lecture-content h3, #lecture-content h4 {
    color: var(--accent); margin: 20px 0 10px;
  }
  #lecture-content h1 { font-size: 24px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
  #lecture-content h2 { font-size: 20px; }
  #lecture-content h3 { font-size: 17px; }
  #lecture-content h4 { font-size: 15px; color: var(--accent3); }
  #lecture-content p { margin: 8px 0; line-height: 1.7; font-size: 14px; }
  #lecture-content ul, #lecture-content ol { margin: 8px 0 8px 24px; line-height: 1.7; font-size: 14px; }
  #lecture-content blockquote {
    border-left: 3px solid var(--accent); padding: 8px 16px;
    margin: 12px 0; background: var(--bg3); border-radius: 0 var(--radius) var(--radius) 0;
    font-size: 13px;
  }
  #lecture-content table {
    width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px;
  }
  #lecture-content th, #lecture-content td {
    padding: 6px 10px; border: 1px solid var(--border); text-align: left;
  }
  #lecture-content th { background: var(--bg3); font-weight: 600; }
  #lecture-content code {
    background: var(--bg3); padding: 2px 6px; border-radius: 4px;
    font-size: 13px; font-family: "Fira Code", monospace;
  }
  #lecture-content pre {
    background: var(--bg3); padding: 12px 16px; border-radius: var(--radius);
    overflow-x: auto; margin: 12px 0; font-size: 13px;
  }
  #lecture-content pre code { background: none; padding: 0; }
  #lecture-content img { max-width: 100%; border-radius: var(--radius); margin: 12px 0; }
  #lecture-content a { color: var(--accent); text-decoration: none; }
  #lecture-content a:hover { text-decoration: underline; }
  #lecture-content hr { border: none; border-top: 1px solid var(--border); margin: 20px 0; }
  #lecture-content details { margin: 12px 0; }
  #lecture-content summary { cursor: pointer; color: var(--accent); font-weight: 600; }

  /* ── 右侧工具栏 ── */
  #toolbar {
    width: var(--toolbar-w); min-width: var(--toolbar-w);
    background: var(--bg2); border-left: 1px solid var(--border);
    display: flex; flex-direction: column; overflow: hidden;
  }
  .tool-tabs {
    display: flex; border-bottom: 1px solid var(--border);
    background: var(--bg);
  }
  .tool-tab {
    flex: 1; padding: 10px 8px; text-align: center;
    font-size: 12px; cursor: pointer; color: var(--fg2);
    border-bottom: 2px solid transparent;
    transition: all 0.15s;
  }
  .tool-tab:hover { color: var(--fg); }
  .tool-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tool-panel { flex:1; overflow-y:auto; padding: 16px; display:none; }
  .tool-panel.active { display:block; }
  .tool-panel h3 { font-size: 14px; color: var(--accent); margin-bottom: 12px; }
  .tool-panel p, .tool-panel li { font-size: 13px; line-height: 1.7; margin: 4px 0; }
  .tool-panel ul { margin-left: 16px; }
  .tool-panel pre {
    background: var(--bg); padding: 10px; border-radius: var(--radius);
    font-size: 12px; white-space: pre-wrap; word-break: break-all;
    border: 1px solid var(--border); margin: 8px 0;
    max-height: 300px; overflow-y: auto;
  }
  .prompt-box {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 12px; margin: 8px 0;
    position: relative;
  }
  .prompt-box pre {
    background: none; border: none; padding: 0;
    font-size: 12px; max-height: 250px;
  }
  .copy-btn {
    position: absolute; top: 8px; right: 8px;
    padding: 3px 8px; font-size: 11px;
    background: var(--accent); color: #fff; border: none;
    border-radius: 4px; cursor: pointer; opacity: 0.8;
  }
  .copy-btn:hover { opacity: 1; }
  .copy-btn.copied { background: var(--accent2); }

  /* ── 欢迎页 ── */
  #welcome {
    flex: 1; display: flex; align-items: center; justify-content: center;
    flex-direction: column; gap: 20px; padding: 40px;
  }
  #welcome h1 { font-size: 28px; color: var(--accent); }
  #welcome p { font-size: 15px; color: var(--fg2); max-width: 500px; text-align: center; line-height: 1.8; }
  .welcome-cards { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; }
  .welcome-card {
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 16px 20px; width: 200px;
    cursor: pointer; transition: all 0.2s; text-align: center;
  }
  .welcome-card:hover { border-color: var(--accent); transform: translateY(-2px); }
  .welcome-card h3 { font-size: 14px; color: var(--accent); margin-bottom: 6px; }
  .welcome-card p { font-size: 12px; color: var(--fg2); }

  /* ── 响应式 ── */
  @media (max-width: 1200px) {
    #toolbar { display: none; }
  }
  @media (max-width: 800px) {
    #sidebar { display: none; }
    #lecture-content { padding: 16px; }
  }

  /* ── 进度条 ── */
  #progress-bar {
    height: 3px; background: var(--bg);
    position: fixed; top: 0; left: 0; right: 0; z-index: 100;
  }
  #progress-fill {
    height: 100%; background: var(--accent); width: 0%;
    transition: width 0.3s;
  }
</style>
</head>
<body>
<div id="progress-bar"><div id="progress-fill"></div></div>

<!-- 侧边栏 -->
<div id="sidebar">
  <div id="sidebar-header">
    <span>🔬</span> Mr.GUO 学习工作台
  </div>
  <div id="nav">
    <div class="nav-item" onclick="loadLearningOS()" style="color:var(--accent3)">
      <span class="nav-id">📖</span> 学习操作系统
    </div>
    {% set ns = namespace(part="") %}
    {% for lec in lectures %}
      {% if lec.part != ns.part %}
        <div class="nav-part">{{ lec.part }}</div>
        {% set ns.part = lec.part %}
      {% endif %}
      <div class="nav-item" data-id="{{ lec.id }}" onclick="loadLecture('{{ lec.id }}')">
        <span class="nav-id">{{ lec.id }}</span>
        {{ lec.title }}
        <span class="nav-status" onclick="event.stopPropagation();toggleDone('{{ lec.id }}')" id="status-{{ lec.id }}">✓</span>
      </div>
    {% endfor %}
  </div>
</div>

<!-- 主内容区 -->
<div id="main">
  <div id="topbar">
    <span id="topbar-title">选择一个讲次开始学习</span>
    <span id="topbar-part"></span>
    <button class="topbar-btn" onclick="toggleToolbar()">🔧 工具栏</button>
  </div>
  <div id="content-area">
    <div id="welcome">
      <h1>🔬 Mr.GUO 学习工作台</h1>
      <p>燃气轮机智能设计与前沿算法自学白皮书 — AI 时代行动版</p>
      <div class="welcome-cards">
        <div class="welcome-card" onclick="loadLearningOS()">
          <h3>📖 开始学习</h3>
          <p>先读学习操作系统</p>
        </div>
        <div class="welcome-card" onclick="loadLecture('00')">
          <h3>🚀 第零章</h3>
          <p>从这里开始</p>
        </div>
        <div class="welcome-card" onclick="loadLecture('01')">
          <h3>⚡ 第 01 讲</h3>
          <p>CR-EI：瞎逛</p>
        </div>
      </div>
    </div>
    <div id="lecture-content" style="display:none"></div>
  </div>
</div>

<!-- 右侧工具栏 -->
<div id="toolbar">
  <div class="tool-tabs">
    <div class="tool-tab active" onclick="switchTab('preview')">预习</div>
    <div class="tool-tab" onclick="switchTab('recall')">回忆</div>
    <div class="tool-tab" onclick="switchTab('review')">收尾</div>
    <div class="tool-tab" onclick="switchTab('task')">任务</div>
    <div class="tool-tab" onclick="switchTab('deposit')">沉淀</div>
  </div>
  <div class="tool-panel active" id="panel-preview">
    <h3>🎯 预习向导</h3>
    <p>选择一个讲次后，这里会显示该讲的预习 Prompt。</p>
  </div>
  <div class="tool-panel" id="panel-recall">
    <h3>🧠 主动回忆 + AI 补漏</h3>
    <p>读完主路后，先自己复述，再把 Prompt 发给 AI。</p>
  </div>
  <div class="tool-panel" id="panel-review">
    <h3>🔍 批判收尾</h3>
    <p>每讲结束时，用这个 Prompt 做深度加工。</p>
  </div>
  <div class="tool-panel" id="panel-task">
    <h3>🛠️ 动手任务</h3>
    <p>选择一个讲次后，这里会显示动手任务。</p>
  </div>
  <div class="tool-panel" id="panel-deposit">
    <h3>📦 沉淀清单</h3>
    <p>选择一个讲次后，这里会显示沉淀清单。</p>
  </div>
</div>

<script>
let currentLid = null;
let doneSet = new Set(JSON.parse(localStorage.getItem('mrGuoDone') || '[]'));

// 初始化已完成状态
doneSet.forEach(id => {
  const el = document.getElementById('status-' + id);
  if (el) el.classList.add('done');
});

function loadLecture(lid) {
  currentLid = lid;
  // 更新侧边栏高亮
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  const navItem = document.querySelector(`.nav-item[data-id="${lid}"]`);
  if (navItem) navItem.classList.add('active');

  document.getElementById('welcome').style.display = 'none';
  const content = document.getElementById('lecture-content');
  content.style.display = 'block';
  content.innerHTML = '<p style="color:var(--fg2)">加载中...</p>';

  fetch('/api/lecture/' + lid)
    .then(r => r.json())
    .then(data => {
      document.getElementById('topbar-title').textContent = data.title;
      document.getElementById('topbar-part').textContent = data.part;
      content.innerHTML = data.html;
      content.scrollTop = 0;

      // 更新工具栏
      document.getElementById('panel-task').innerHTML =
        '<h3>🛠️ 动手任务</h3>' + (data.task || '<p>本讲暂无动手任务</p>');
      document.getElementById('panel-deposit').innerHTML =
        '<h3>📦 沉淀清单</h3>' + (data.deposit || '<p>本讲暂无沉淀清单</p>');

      // 更新进度条
      updateProgress();
    });

  // 加载三个 Prompt
  ['preview', 'recall', 'review'].forEach(kind => {
    fetch('/api/prompt/' + lid + '/' + kind)
      .then(r => r.json())
      .then(data => {
        const panel = document.getElementById('panel-' + kind);
        const titles = {preview:'🎯 预习向导', recall:'🧠 主动回忆 + AI 补漏', review:'🔍 批判收尾'};
        panel.innerHTML = `<h3>${titles[kind]}</h3>
          <div class="prompt-box">
            <button class="copy-btn" onclick="copyPrompt(this)">复制</button>
            <pre>${escapeHtml(data.text)}</pre>
          </div>`;
      });
  });
}

function loadLearningOS() {
  currentLid = null;
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  document.getElementById('welcome').style.display = 'none';
  const content = document.getElementById('lecture-content');
  content.style.display = 'block';
  content.innerHTML = '<p style="color:var(--fg2)">加载中...</p>';

  fetch('/api/learning_os')
    .then(r => r.json())
    .then(data => {
      document.getElementById('topbar-title').textContent = '学习操作系统';
      document.getElementById('topbar-part').textContent = '怎么用这本书';
      content.innerHTML = data.html;
      content.scrollTop = 0;
    });
}

function switchTab(kind) {
  document.querySelectorAll('.tool-tab').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tool-panel').forEach(el => el.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('panel-' + kind).classList.add('active');
}

function copyPrompt(btn) {
  const pre = btn.parentElement.querySelector('pre');
  navigator.clipboard.writeText(pre.textContent).then(() => {
    btn.textContent = '已复制 ✓';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = '复制'; btn.classList.remove('copied'); }, 2000);
  });
}

function toggleDone(id) {
  const el = document.getElementById('status-' + id);
  if (doneSet.has(id)) {
    doneSet.delete(id);
    el.classList.remove('done');
  } else {
    doneSet.add(id);
    el.classList.add('done');
  }
  localStorage.setItem('mrGuoDone', JSON.stringify([...doneSet]));
  updateProgress();
}

function updateProgress() {
  const total = document.querySelectorAll('.nav-item[data-id]').length;
  const done = doneSet.size;
  const pct = total > 0 ? (done / total * 100) : 0;
  document.getElementById('progress-fill').style.width = pct + '%';
}

function toggleToolbar() {
  const tb = document.getElementById('toolbar');
  tb.style.display = tb.style.display === 'none' ? 'flex' : 'none';
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// 初始进度
updateProgress();
</script>
</body>
</html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

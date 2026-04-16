#!/usr/bin/env python3
"""
deai web panel — local web UI for the deai image processing skill.
Usage: python3 server.py [--port 8890]
"""

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs
import uuid
import zipfile
import io

# Add parent to path so we can import deai
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import deai

UPLOAD_DIR = Path(tempfile.mkdtemp(prefix="deai_"))
STATIC_DIR = SCRIPT_DIR.parent / "web"

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DeAI — 去除 AI 痕迹</title>
<style>
:root {
  --bg: #0f1117;
  --surface: #1a1d27;
  --surface2: #242836;
  --border: #2e3348;
  --text: #e4e4e7;
  --text2: #9ca3af;
  --accent: #6366f1;
  --accent-hover: #818cf8;
  --success: #22c55e;
  --warning: #f59e0b;
  --radius: 12px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}

/* Header */
.header {
  padding: 20px 32px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 16px;
}
.header h1 {
  font-size: 20px;
  font-weight: 600;
  background: linear-gradient(135deg, #6366f1, #a855f7);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.header .badge {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--surface2);
  color: var(--text2);
  font-weight: 500;
}

/* Layout */
.main {
  display: grid;
  grid-template-columns: 320px 1fr;
  min-height: calc(100vh - 65px);
}

/* Sidebar */
.sidebar {
  background: var(--surface);
  border-right: 1px solid var(--border);
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
}

.section-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--text2);
  margin-bottom: 8px;
}

/* Upload area */
.upload-zone {
  border: 2px dashed var(--border);
  border-radius: var(--radius);
  padding: 32px 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}
.upload-zone:hover, .upload-zone.drag-over {
  border-color: var(--accent);
  background: rgba(99, 102, 241, 0.05);
}
.upload-zone .icon {
  font-size: 32px;
  margin-bottom: 8px;
  opacity: 0.5;
}
.upload-zone p {
  font-size: 13px;
  color: var(--text2);
}
.upload-zone input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}
.upload-preview {
  display: none;
  position: relative;
}
.upload-preview img {
  width: 100%;
  border-radius: 8px;
  border: 1px solid var(--border);
}
.upload-preview .remove-btn {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: rgba(0,0,0,0.7);
  color: white;
  border: none;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Controls */
.control-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.toggle-group {
  display: flex;
  gap: 4px;
  background: var(--bg);
  padding: 3px;
  border-radius: 8px;
}
.toggle-btn {
  flex: 1;
  padding: 7px 4px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text2);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.toggle-btn.active {
  background: var(--accent);
  color: white;
}
.toggle-btn:hover:not(.active) {
  color: var(--text);
  background: var(--surface2);
}

.select-control {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
  -webkit-appearance: none;
}
.select-control:focus {
  outline: none;
  border-color: var(--accent);
}

.checkbox-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
}
.checkbox-row input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
}
.checkbox-row label {
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
}
.checkbox-row .hint {
  font-size: 11px;
  color: var(--text2);
}

/* Process button */
.process-btn {
  width: 100%;
  padding: 12px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  margin-top: auto;
}
.process-btn:hover:not(:disabled) {
  background: var(--accent-hover);
  transform: translateY(-1px);
}
.process-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.process-btn.processing {
  background: var(--surface2);
  position: relative;
  overflow: hidden;
}
.process-btn.processing::after {
  content: '';
  position: absolute;
  left: -100%;
  top: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(99,102,241,0.3), transparent);
  animation: shimmer 1.5s infinite;
}
@keyframes shimmer {
  100% { left: 100%; }
}

.download-btn {
  width: 100%;
  padding: 10px;
  border: 1px solid var(--success);
  border-radius: 8px;
  background: transparent;
  color: var(--success);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  display: none;
  text-decoration: none;
  text-align: center;
}
.download-btn:hover {
  background: rgba(34, 197, 94, 0.1);
}

/* Canvas area */
.canvas-area {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.canvas-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.view-toggle {
  display: flex;
  gap: 4px;
  background: var(--surface);
  padding: 3px;
  border-radius: 8px;
}

.canvas-info {
  margin-left: auto;
  font-size: 12px;
  color: var(--text2);
}

/* Compare view */
.compare-container {
  flex: 1;
  position: relative;
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--surface);
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 400px;
}

.compare-container .placeholder {
  text-align: center;
  color: var(--text2);
}
.compare-container .placeholder .icon { font-size: 48px; opacity: 0.3; }
.compare-container .placeholder p { margin-top: 12px; font-size: 14px; }

/* Side by side */
.side-by-side {
  display: none;
  width: 100%;
  height: 100%;
}
.side-by-side .panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px;
  gap: 8px;
}
.side-by-side .panel:first-child {
  border-right: 1px solid var(--border);
}
.side-by-side .panel-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text2);
}
.side-by-side img {
  max-width: 100%;
  max-height: calc(100vh - 200px);
  object-fit: contain;
  border-radius: 6px;
}

/* Slider compare */
.slider-compare {
  display: none;
  position: relative;
  width: 100%;
  height: 100%;
}
.slider-compare img {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}
.slider-compare .img-after {
  clip-path: inset(0 0 0 50%);
}
.slider-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 3px;
  background: white;
  cursor: ew-resize;
  z-index: 10;
  box-shadow: 0 0 8px rgba(0,0,0,0.5);
}
.slider-handle::after {
  content: '⟷';
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 32px;
  height: 32px;
  background: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: #333;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}
.slider-label {
  position: absolute;
  top: 12px;
  padding: 4px 10px;
  background: rgba(0,0,0,0.7);
  color: white;
  font-size: 11px;
  font-weight: 600;
  border-radius: 4px;
  z-index: 5;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.slider-label.before { left: 12px; }
.slider-label.after { right: 12px; }

/* Single view */
.single-view {
  display: none;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.single-view img {
  max-width: 100%;
  max-height: calc(100vh - 200px);
  object-fit: contain;
  border-radius: 6px;
}

/* Steps log */
.steps-log {
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  max-height: 160px;
  overflow-y: auto;
}
.steps-log .step {
  font-size: 12px;
  font-family: 'SF Mono', Menlo, monospace;
  padding: 3px 0;
  color: var(--text2);
}
.steps-log .step::before {
  content: '\2713 ';
  color: var(--success);
}

/* Scan report */
.scan-report {
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  margin-top: 8px;
}
.scan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.scan-score {
  display: flex;
  align-items: center;
  gap: 12px;
}
.score-ring {
  width: 56px;
  height: 56px;
  position: relative;
}
.score-ring svg {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}
.score-ring .bg {
  fill: none;
  stroke: var(--surface2);
  stroke-width: 5;
}
.score-ring .fg {
  fill: none;
  stroke-width: 5;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.6s ease;
}
.score-ring .value {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  font-weight: 700;
}
.score-label {
  font-size: 13px;
  font-weight: 600;
}
.risk-low { color: var(--success); }
.risk-medium { color: var(--warning); }
.risk-high { color: #ef4444; }
.scan-checks {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.scan-check {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: var(--bg);
  border-radius: 8px;
}
.check-icon {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}
.check-icon.ok { background: rgba(34,197,94,0.15); color: var(--success); }
.check-icon.warn { background: rgba(245,158,11,0.15); color: var(--warning); }
.check-icon.bad { background: rgba(239,68,68,0.15); color: #ef4444; }
.check-info { flex: 1; min-width: 0; }
.check-name {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 2px;
}
.check-detail {
  font-size: 11px;
  color: var(--text2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.check-score {
  font-size: 11px;
  font-weight: 600;
  color: var(--text2);
  flex-shrink: 0;
}
.scan-tip {
  margin-top: 12px;
  padding: 10px 12px;
  background: rgba(99,102,241,0.08);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text2);
  line-height: 1.5;
}
.scan-btn {
  width: 100%;
  padding: 10px;
  border: 1px solid var(--accent);
  border-radius: 8px;
  background: transparent;
  color: var(--accent);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.scan-btn:hover:not(:disabled) {
  background: rgba(99,102,241,0.1);
}
.scan-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.scan-btn.scanning {
  position: relative;
  overflow: hidden;
}
.scan-btn.scanning::after {
  content: '';
  position: absolute;
  left: -100%;
  top: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(99,102,241,0.2), transparent);
  animation: shimmer 1.5s infinite;
}

/* Batch area */
.batch-section {
  display: none;
  border-top: 1px solid var(--border);
  padding-top: 16px;
}
.batch-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
}
.batch-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: var(--bg);
  border-radius: 6px;
  font-size: 12px;
}
.batch-item .name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.batch-item .status { font-size: 11px; color: var(--text2); }
.batch-item .status.done { color: var(--success); }
.batch-item .status.processing { color: var(--warning); }

/* Responsive */
@media (max-width: 900px) {
  .main { grid-template-columns: 1fr; }
  .sidebar { border-right: none; border-bottom: 1px solid var(--border); }
}
</style>
</head>
<body>

<div class="header">
  <h1>DeAI</h1>
  <span class="badge">v1.1 — Photo + Illustration</span>
</div>

<div class="main">
  <!-- Sidebar -->
  <div class="sidebar">
    <!-- Upload -->
    <div>
      <div class="section-label">输入图片</div>
      <div class="upload-zone" id="uploadZone">
        <div class="icon">📷</div>
        <p>拖拽图片到这里<br>或点击选择文件</p>
        <input type="file" id="fileInput" accept="image/*" multiple>
      </div>
      <div class="upload-preview" id="uploadPreview">
        <img id="previewImg" src="">
        <button class="remove-btn" onclick="clearUpload()">✕</button>
      </div>
    </div>

    <!-- Mode -->
    <div class="control-group">
      <div class="section-label">处理模式</div>
      <div class="toggle-group" id="modeGroup">
        <button class="toggle-btn active" data-value="photo" onclick="setMode('photo')">仿真照片</button>
        <button class="toggle-btn" data-value="illustration" onclick="setMode('illustration')">插画/卡通</button>
      </div>
    </div>

    <!-- Preset -->
    <div class="control-group">
      <div class="section-label">处理强度</div>
      <div class="toggle-group" id="presetGroup">
        <button class="toggle-btn" data-value="light" onclick="setPreset('light')">轻度</button>
        <button class="toggle-btn active" data-value="medium" onclick="setPreset('medium')">中度</button>
        <button class="toggle-btn" data-value="heavy" onclick="setPreset('heavy')">重度</button>
      </div>
    </div>

    <!-- Camera -->
    <div class="control-group">
      <div class="section-label">相机配置 (EXIF + 量化表)</div>
      <select class="select-control" id="cameraSelect">
        <option value="iphone15">iPhone 15 Pro Max — 手机/社媒</option>
        <option value="canon_r5">Canon EOS R5 — 专业/人像</option>
        <option value="sony_a7iv">Sony A7 IV — 通用全画幅</option>
        <option value="nikon_z8">Nikon Z 8 — 高端/风光</option>
      </select>
    </div>

    <!-- Watermark -->
    <div class="control-group">
      <div class="checkbox-row">
        <input type="checkbox" id="watermarkCheck">
        <label for="watermarkCheck">去除水印</label>
      </div>
      <select class="select-control" id="watermarkPos" disabled>
        <option value="auto">自动检测</option>
        <option value="BR">右下角</option>
        <option value="BL">左下角</option>
        <option value="TR">右上角</option>
        <option value="TL">左上角</option>
      </select>
    </div>

    <!-- Batch -->
    <div class="batch-section" id="batchSection">
      <div class="section-label">批量处理</div>
      <div class="batch-list" id="batchList"></div>
    </div>

    <!-- Actions -->
    <div style="margin-top:auto; display:flex; flex-direction:column; gap:8px;">
      <button class="scan-btn" id="scanBtn" disabled onclick="scanImage()">
        AI 检测风险扫描
      </button>
      <button class="process-btn" id="scanFixBtn" disabled onclick="scanAndFix()"
        style="background:linear-gradient(135deg,#6366f1,#a855f7); display:none;">
        智能修复 — 根据检测结果自动调参
      </button>
      <button class="process-btn" id="processBtn" disabled onclick="processImage()">
        开始处理
      </button>
      <a class="download-btn" id="downloadBtn" download>下载处理后的图片</a>
      <a class="download-btn" id="downloadZipBtn" style="display:none; border-color:#6366f1; color:#6366f1;">
        打包下载全部 (ZIP)
      </a>
      <div id="batchProgress" style="display:none; font-size:12px; color:var(--text2); text-align:center;"></div>
    </div>
  </div>

  <!-- Canvas -->
  <div class="canvas-area">
    <div class="canvas-toolbar">
      <div class="view-toggle">
        <button class="toggle-btn active" data-value="slider" onclick="setView('slider')">滑动对比</button>
        <button class="toggle-btn" data-value="side" onclick="setView('side')">并排对比</button>
        <button class="toggle-btn" data-value="before" onclick="setView('before')">处理前</button>
        <button class="toggle-btn" data-value="after" onclick="setView('after')">处理后</button>
      </div>
      <div class="canvas-info" id="canvasInfo"></div>
    </div>

    <div class="compare-container" id="compareContainer">
      <div class="placeholder" id="placeholder">
        <div class="icon">🖼</div>
        <p>上传图片开始处理</p>
      </div>

      <!-- Slider compare -->
      <div class="slider-compare" id="sliderView">
        <span class="slider-label before">处理前</span>
        <span class="slider-label after">处理后</span>
        <img class="img-before" id="sliderBefore" src="">
        <img class="img-after" id="sliderAfter" src="">
        <div class="slider-handle" id="sliderHandle"></div>
      </div>

      <!-- Side by side -->
      <div class="side-by-side" id="sideView">
        <div class="panel">
          <span class="panel-label">处理前</span>
          <img id="sideBefore" src="">
        </div>
        <div class="panel">
          <span class="panel-label">处理后</span>
          <img id="sideAfter" src="">
        </div>
      </div>

      <!-- Single views -->
      <div class="single-view" id="beforeView">
        <img id="singleBefore" src="">
      </div>
      <div class="single-view" id="afterView">
        <img id="singleAfter" src="">
      </div>
    </div>

    <!-- Steps log -->
    <div class="steps-log" id="stepsLog"></div>

    <!-- Scan report -->
    <div class="scan-report" id="scanReport">
      <div class="scan-header">
        <div class="scan-score">
          <div class="score-ring">
            <svg viewBox="0 0 36 36">
              <circle class="bg" cx="18" cy="18" r="15.9"/>
              <circle class="fg" id="scoreRing" cx="18" cy="18" r="15.9"
                stroke-dasharray="100" stroke-dashoffset="100"/>
            </svg>
            <span class="value" id="scoreValue">0</span>
          </div>
          <div>
            <div class="score-label" id="riskLabel">--</div>
            <div style="font-size:11px; color:var(--text2);">AI 检测风险</div>
          </div>
        </div>
      </div>
      <div class="scan-checks" id="scanChecks"></div>
      <div class="scan-tip" id="scanTip"></div>
    </div>
  </div>
</div>

<script>
// State
let currentMode = 'photo';
let currentPreset = 'medium';
let currentView = 'slider';
let uploadedFile = null;
let beforeUrl = null;
let afterUrl = null;
let batchFiles = [];
let batchOutputIds = [];  // track all processed output IDs for zip download

// Watermark toggle
document.getElementById('watermarkCheck').addEventListener('change', (e) => {
  document.getElementById('watermarkPos').disabled = !e.target.checked;
});

// File upload
const uploadZone = document.getElementById('uploadZone');
const fileInput = document.getElementById('fileInput');

['dragenter', 'dragover'].forEach(e => {
  uploadZone.addEventListener(e, (ev) => { ev.preventDefault(); uploadZone.classList.add('drag-over'); });
});
['dragleave', 'drop'].forEach(e => {
  uploadZone.addEventListener(e, (ev) => { ev.preventDefault(); uploadZone.classList.remove('drag-over'); });
});
uploadZone.addEventListener('drop', (e) => {
  const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
  if (files.length > 0) handleFiles(files);
});
fileInput.addEventListener('change', () => {
  const files = Array.from(fileInput.files).filter(f => f.type.startsWith('image/'));
  if (files.length > 0) handleFiles(files);
});

function handleFiles(files) {
  if (files.length === 1) {
    uploadedFile = files[0];
    batchFiles = [];
    showPreview(files[0]);
    document.getElementById('batchSection').style.display = 'none';
  } else {
    // Batch mode
    uploadedFile = files[0];
    batchFiles = files;
    showPreview(files[0]);
    showBatchList(files);
  }
  document.getElementById('processBtn').disabled = false;
  document.getElementById('scanBtn').disabled = false;
}

function showPreview(file) {
  const reader = new FileReader();
  reader.onload = (e) => {
    beforeUrl = e.target.result;
    document.getElementById('previewImg').src = beforeUrl;
    document.getElementById('uploadPreview').style.display = 'block';
    document.getElementById('uploadZone').style.display = 'none';
    // Show in canvas
    showBeforeOnly();
  };
  reader.readAsDataURL(file);
}

function showBeforeOnly() {
  document.getElementById('placeholder').style.display = 'none';
  document.getElementById('sliderView').style.display = 'none';
  document.getElementById('sideView').style.display = 'none';
  document.getElementById('afterView').style.display = 'none';
  document.getElementById('beforeView').style.display = 'flex';
  document.getElementById('singleBefore').src = beforeUrl;
}

function clearUpload() {
  uploadedFile = null;
  batchFiles = [];
  beforeUrl = null;
  afterUrl = null;
  document.getElementById('uploadPreview').style.display = 'none';
  document.getElementById('uploadZone').style.display = 'block';
  document.getElementById('processBtn').disabled = true;
  document.getElementById('scanBtn').disabled = true;
  document.getElementById('scanFixBtn').disabled = true;
  document.getElementById('scanFixBtn').style.display = 'none';
  document.getElementById('downloadBtn').style.display = 'none';
  document.getElementById('downloadZipBtn').style.display = 'none';
  document.getElementById('batchProgress').style.display = 'none';
  document.getElementById('stepsLog').style.display = 'none';
  document.getElementById('scanReport').style.display = 'none';
  document.getElementById('batchSection').style.display = 'none';
  batchOutputIds = [];
  document.getElementById('placeholder').style.display = 'block';
  document.getElementById('sliderView').style.display = 'none';
  document.getElementById('sideView').style.display = 'none';
  document.getElementById('beforeView').style.display = 'none';
  document.getElementById('afterView').style.display = 'none';
  document.getElementById('canvasInfo').textContent = '';
  fileInput.value = '';
}

function showBatchList(files) {
  const section = document.getElementById('batchSection');
  const list = document.getElementById('batchList');
  section.style.display = 'block';
  list.innerHTML = files.map((f, i) => `
    <div class="batch-item" id="batch-${i}">
      <span class="name">${f.name}</span>
      <span class="status" id="batch-status-${i}">等待中</span>
    </div>
  `).join('');
}

// Mode / Preset
function setMode(mode) {
  currentMode = mode;
  document.querySelectorAll('#modeGroup .toggle-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.value === mode);
  });
}

function setPreset(preset) {
  currentPreset = preset;
  document.querySelectorAll('#presetGroup .toggle-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.value === preset);
  });
}

function setView(view) {
  currentView = view;
  document.querySelectorAll('.view-toggle .toggle-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.value === view);
  });
  updateView();
}

function updateView() {
  const hasAfter = !!afterUrl;
  document.getElementById('sliderView').style.display = 'none';
  document.getElementById('sideView').style.display = 'none';
  document.getElementById('beforeView').style.display = 'none';
  document.getElementById('afterView').style.display = 'none';

  if (!hasAfter) {
    if (beforeUrl) showBeforeOnly();
    return;
  }

  switch (currentView) {
    case 'slider':
      document.getElementById('sliderView').style.display = 'block';
      document.getElementById('sliderBefore').src = beforeUrl;
      document.getElementById('sliderAfter').src = afterUrl;
      break;
    case 'side':
      document.getElementById('sideView').style.display = 'flex';
      document.getElementById('sideBefore').src = beforeUrl;
      document.getElementById('sideAfter').src = afterUrl;
      break;
    case 'before':
      document.getElementById('beforeView').style.display = 'flex';
      document.getElementById('singleBefore').src = beforeUrl;
      break;
    case 'after':
      document.getElementById('afterView').style.display = 'flex';
      document.getElementById('singleAfter').src = afterUrl;
      break;
  }
}

// Slider drag
const sliderHandle = document.getElementById('sliderHandle');
let isDragging = false;

sliderHandle.addEventListener('mousedown', () => isDragging = true);
document.addEventListener('mouseup', () => isDragging = false);
document.addEventListener('mousemove', (e) => {
  if (!isDragging) return;
  const container = document.getElementById('sliderView');
  const rect = container.getBoundingClientRect();
  let x = (e.clientX - rect.left) / rect.width * 100;
  x = Math.max(5, Math.min(95, x));
  sliderHandle.style.left = x + '%';
  document.getElementById('sliderAfter').style.clipPath = `inset(0 0 0 ${x}%)`;
});

// Touch support
sliderHandle.addEventListener('touchstart', (e) => { isDragging = true; e.preventDefault(); });
document.addEventListener('touchend', () => isDragging = false);
document.addEventListener('touchmove', (e) => {
  if (!isDragging) return;
  const container = document.getElementById('sliderView');
  const rect = container.getBoundingClientRect();
  let x = (e.touches[0].clientX - rect.left) / rect.width * 100;
  x = Math.max(5, Math.min(95, x));
  sliderHandle.style.left = x + '%';
  document.getElementById('sliderAfter').style.clipPath = `inset(0 0 0 ${x}%)`;
});

// Process
async function processImage() {
  if (!uploadedFile) return;

  const btn = document.getElementById('processBtn');
  btn.disabled = true;
  btn.classList.add('processing');
  btn.textContent = '处理中...';

  const camera = document.getElementById('cameraSelect').value;
  const watermarkEnabled = document.getElementById('watermarkCheck').checked;
  const watermarkPos = watermarkEnabled ? document.getElementById('watermarkPos').value : '';

  // Resolve preset name
  let preset = currentPreset;
  if (currentMode === 'illustration') {
    preset = 'illust-' + preset;
  }

  if (batchFiles.length > 1) {
    // Batch processing
    batchOutputIds = [];
    const progressEl = document.getElementById('batchProgress');
    progressEl.style.display = 'block';

    for (let i = 0; i < batchFiles.length; i++) {
      document.getElementById(`batch-status-${i}`).textContent = '处理中...';
      document.getElementById(`batch-status-${i}`).className = 'status processing';
      progressEl.textContent = `处理中 ${i + 1} / ${batchFiles.length}...`;

      const result = await uploadAndProcess(batchFiles[i], preset, camera, watermarkPos);

      document.getElementById(`batch-status-${i}`).textContent = result.success ? '完成' : '失败';
      document.getElementById(`batch-status-${i}`).className = 'status ' + (result.success ? 'done' : '');

      if (result.success) {
        batchOutputIds.push(result.output_id);
      }

      // Show last processed in compare view
      if (result.success && i === batchFiles.length - 1) {
        afterUrl = result.outputUrl;
        showResult(result);
      }
    }

    progressEl.textContent = `全部完成: ${batchOutputIds.length} / ${batchFiles.length} 张`;

    // Show zip download button
    if (batchOutputIds.length > 0) {
      const zipBtn = document.getElementById('downloadZipBtn');
      zipBtn.style.display = 'block';
      zipBtn.href = '/api/download-zip?ids=' + batchOutputIds.join(',');
      zipBtn.setAttribute('download', 'deai_batch.zip');
      // Single file download shows last one
      const dlBtn = document.getElementById('downloadBtn');
      dlBtn.style.display = 'block';
      dlBtn.textContent = `下载最后一张`;
    }
  } else {
    const result = await uploadAndProcess(uploadedFile, preset, camera, watermarkPos);
    if (result.success) {
      afterUrl = result.outputUrl;
      showResult(result);
    } else {
      alert('处理失败: ' + (result.error || '未知错误'));
    }
  }

  btn.disabled = false;
  btn.classList.remove('processing');
  btn.textContent = '重新处理';
}

async function uploadAndProcess(file, preset, camera, watermark) {
  const formData = new FormData();
  formData.append('image', file);
  formData.append('preset', preset);
  formData.append('camera', camera);
  if (watermark) formData.append('watermark', watermark);

  try {
    const resp = await fetch('/api/process', { method: 'POST', body: formData });
    const data = await resp.json();
    if (data.success) {
      data.outputUrl = '/api/download/' + data.output_id;
    }
    return data;
  } catch (e) {
    return { success: false, error: e.message };
  }
}

function showResult(result) {
  document.getElementById('placeholder').style.display = 'none';
  currentView = 'slider';
  document.querySelectorAll('.view-toggle .toggle-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.value === 'slider');
  });
  updateView();

  // Download button
  const dlBtn = document.getElementById('downloadBtn');
  dlBtn.href = result.outputUrl;
  dlBtn.download = uploadedFile.name.replace(/\.[^.]+$/, '_deai.jpg');
  dlBtn.style.display = 'block';

  // Steps log
  if (result.steps) {
    const log = document.getElementById('stepsLog');
    log.style.display = 'block';
    log.innerHTML = result.steps.map(s => `<div class="step">${s}</div>`).join('');
  }

  // Info
  const info = document.getElementById('canvasInfo');
  info.textContent = `${result.mode || ''} · ${result.preset || ''} · ${result.camera || ''}`;
}

// Scan
async function scanImage() {
  if (!uploadedFile) return;

  const btn = document.getElementById('scanBtn');
  btn.disabled = true;
  btn.classList.add('scanning');
  btn.textContent = 'AI 扫描中...';
  document.getElementById('scanReport').style.display = 'none';

  const formData = new FormData();
  formData.append('image', uploadedFile);

  try {
    const resp = await fetch('/api/scan', { method: 'POST', body: formData });
    const data = await resp.json();

    if (data.success) {
      renderScanReport(data.report);
    } else {
      alert('扫描失败: ' + (data.error || '未知错误'));
    }
  } catch (e) {
    alert('扫描失败: ' + e.message);
  }

  btn.disabled = false;
  btn.classList.remove('scanning');
  btn.textContent = 'AI 检测风险扫描';
}

function renderScanReport(report) {
  const panel = document.getElementById('scanReport');
  panel.style.display = 'block';

  // Score ring
  const score = report.risk_score;
  const circumference = 2 * Math.PI * 15.9;
  const offset = circumference - (score / 100) * circumference;
  const ring = document.getElementById('scoreRing');
  ring.style.strokeDasharray = circumference;
  ring.style.strokeDashoffset = offset;

  const riskClass = score >= 60 ? 'risk-high' : (score >= 30 ? 'risk-medium' : 'risk-low');
  const riskColor = score >= 60 ? '#ef4444' : (score >= 30 ? '#f59e0b' : '#22c55e');
  ring.style.stroke = riskColor;

  document.getElementById('scoreValue').textContent = score;
  document.getElementById('scoreValue').className = 'value ' + riskClass;

  const riskLabels = { 'LOW': '低风险', 'MEDIUM': '中风险', 'HIGH': '高风险' };
  const label = document.getElementById('riskLabel');
  label.textContent = riskLabels[report.risk_level] || report.risk_level;
  label.className = 'score-label ' + riskClass;

  // Checks
  const checksEl = document.getElementById('scanChecks');
  checksEl.innerHTML = '';
  for (const [name, info] of Object.entries(report.checks)) {
    const iconClass = info.risk === 'HIGH' ? 'bad' : (info.risk === 'MEDIUM' ? 'warn' : 'ok');
    const iconText = info.risk === 'HIGH' ? '!!' : (info.risk === 'MEDIUM' ? '!' : 'OK');
    checksEl.innerHTML += `
      <div class="scan-check">
        <div class="check-icon ${iconClass}">${iconText}</div>
        <div class="check-info">
          <div class="check-name">${name}</div>
          <div class="check-detail" title="${info.detail}">${info.detail}</div>
        </div>
        <div class="check-score">${info.score}/${info.max}</div>
      </div>`;
  }

  // Tip
  const tipEl = document.getElementById('scanTip');
  if (score >= 60) {
    tipEl.textContent = 'AI 检测风险较高,建议点击「智能修复」自动针对高分因子调参处理。';
  } else if (score >= 30) {
    tipEl.textContent = 'AI 检测风险中等,建议点击「智能修复」进一步降低检测风险。';
  } else {
    tipEl.textContent = 'AI 检测风险较低,图片已接近真实相机/手绘效果。';
  }

  // Show smart-fix button if risk is not already low
  const fixBtn = document.getElementById('scanFixBtn');
  if (score > 15) {
    fixBtn.style.display = 'block';
    fixBtn.disabled = false;
  }
}

function renderScanComparison(before, after, targeted) {
  const panel = document.getElementById('scanReport');
  panel.style.display = 'block';

  const scoreBefore = before.risk_score;
  const scoreAfter = after.risk_score;
  const drop = scoreBefore - scoreAfter;

  // Update ring to show after score
  const circumference = 2 * Math.PI * 15.9;
  const offset = circumference - (scoreAfter / 100) * circumference;
  const ring = document.getElementById('scoreRing');
  ring.style.strokeDasharray = circumference;
  ring.style.strokeDashoffset = offset;

  const riskClass = scoreAfter >= 60 ? 'risk-high' : (scoreAfter >= 30 ? 'risk-medium' : 'risk-low');
  const riskColor = scoreAfter >= 60 ? '#ef4444' : (scoreAfter >= 30 ? '#f59e0b' : '#22c55e');
  ring.style.stroke = riskColor;

  document.getElementById('scoreValue').textContent = scoreAfter;
  document.getElementById('scoreValue').className = 'value ' + riskClass;

  const riskLabels = { 'LOW': '低风险', 'MEDIUM': '中风险', 'HIGH': '高风险' };
  const label = document.getElementById('riskLabel');
  label.textContent = `${riskLabels[after.risk_level] || after.risk_level} (${scoreBefore} -> ${scoreAfter}, -${drop})`;
  label.className = 'score-label ' + riskClass;

  // Checks: show before vs after comparison
  const checksEl = document.getElementById('scanChecks');
  checksEl.innerHTML = '';
  for (const [name, afterInfo] of Object.entries(after.checks)) {
    const beforeInfo = before.checks[name] || { score: 0, max: afterInfo.max };
    const improved = beforeInfo.score > afterInfo.score;
    const iconClass = afterInfo.risk === 'HIGH' ? 'bad' : (afterInfo.risk === 'MEDIUM' ? 'warn' : 'ok');
    const iconText = afterInfo.risk === 'HIGH' ? '!!' : (afterInfo.risk === 'MEDIUM' ? '!' : 'OK');
    const changeText = improved ? ` (${beforeInfo.score} -> ${afterInfo.score})` : '';
    checksEl.innerHTML += `
      <div class="scan-check">
        <div class="check-icon ${iconClass}">${iconText}</div>
        <div class="check-info">
          <div class="check-name">${name}${improved ? ' <span style="color:var(--success);font-size:10px;">-' + (beforeInfo.score - afterInfo.score) + '</span>' : ''}</div>
          <div class="check-detail" title="${afterInfo.detail}">${afterInfo.detail}</div>
        </div>
        <div class="check-score">${afterInfo.score}/${afterInfo.max}</div>
      </div>`;
  }

  // Targeted adjustments
  const tipEl = document.getElementById('scanTip');
  if (targeted && targeted.length > 0) {
    tipEl.innerHTML = '<strong>针对性调参:</strong><br>' + targeted.map(t => '- ' + t).join('<br>');
  } else {
    tipEl.textContent = `风险分已降低 ${drop} 分。`;
  }
}

// Smart scan-and-fix
async function scanAndFix() {
  if (!uploadedFile) return;

  const btn = document.getElementById('scanFixBtn');
  btn.disabled = true;
  btn.textContent = '扫描 + 智能修复中...';
  btn.classList.add('processing');

  const camera = document.getElementById('cameraSelect').value;
  const watermarkEnabled = document.getElementById('watermarkCheck').checked;
  const watermarkPos = watermarkEnabled ? document.getElementById('watermarkPos').value : '';

  let preset = currentPreset;
  if (currentMode === 'illustration') {
    preset = 'illust-' + preset;
  }

  const formData = new FormData();
  formData.append('image', uploadedFile);
  formData.append('preset', preset);
  formData.append('camera', camera);
  if (watermarkPos) formData.append('watermark', watermarkPos);

  try {
    const resp = await fetch('/api/scan-fix', { method: 'POST', body: formData });
    const data = await resp.json();

    if (data.success) {
      afterUrl = '/api/download/' + data.output_id;

      // Show compare view
      document.getElementById('placeholder').style.display = 'none';
      currentView = 'slider';
      document.querySelectorAll('.view-toggle .toggle-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.value === 'slider');
      });
      updateView();

      // Download button
      const dlBtn = document.getElementById('downloadBtn');
      dlBtn.href = afterUrl;
      dlBtn.download = uploadedFile.name.replace(/\.[^.]+$/, '_deai.jpg');
      dlBtn.style.display = 'block';

      // Steps log
      if (data.steps) {
        const log = document.getElementById('stepsLog');
        log.style.display = 'block';
        log.innerHTML = data.steps.map(s => '<div class="step">' + s + '</div>').join('');
      }

      // Info
      document.getElementById('canvasInfo').textContent =
        `${data.mode || ''} · ${data.preset || ''} · ${data.camera || ''} · 智能修复`;

      // Show before/after scan comparison
      renderScanComparison(data.scan_before, data.scan_after, data.targeted);
    } else {
      alert('智能修复失败: ' + (data.error || '未知错误'));
    }
  } catch (e) {
    alert('智能修复失败: ' + e.message);
  }

  btn.disabled = false;
  btn.classList.remove('processing');
  btn.textContent = '智能修复 — 根据检测结果自动调参';
}
</script>

</body>
</html>
"""


class DeAIHandler(BaseHTTPRequestHandler):
    outputs = {}  # output_id -> filepath

    def log_message(self, format, *args):
        # Quieter logging
        pass

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))

        elif self.path.startswith('/api/download-zip'):
            # Download all processed images as a zip
            # IDs passed as query: /api/download-zip?ids=abc,def,ghi
            query_str = self.path.split('?', 1)[1] if '?' in self.path else ''
            params = parse_qs(query_str)
            ids = params.get('ids', [''])[0].split(',')
            ids = [i.strip() for i in ids if i.strip()]

            if not ids:
                self.send_response(400)
                self.end_headers()
                return

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for oid in ids:
                    filepath = self.outputs.get(oid)
                    if filepath and os.path.exists(filepath):
                        arcname = os.path.basename(filepath).replace(f'output_{oid}', f'deai_{oid}')
                        zf.write(filepath, arcname)

            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', 'attachment; filename="deai_batch.zip"')
            self.end_headers()
            self.wfile.write(buf.getvalue())

        elif self.path.startswith('/api/download/'):
            output_id = self.path.split('/')[-1]
            filepath = self.outputs.get(output_id)
            if filepath and os.path.exists(filepath):
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Disposition', f'attachment; filename="deai_{output_id}.jpg"')
                self.end_headers()
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def _parse_multipart(self):
        """Parse multipart/form-data without the deprecated cgi module."""
        content_type = self.headers.get('Content-Type', '')
        # Extract boundary
        match = re.search(r'boundary=(.+?)(?:;|$)', content_type)
        if not match:
            return {}, {}
        boundary = match.group(1).strip().encode()

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        fields = {}  # name -> value (str)
        files = {}   # name -> (filename, data)

        # Split by boundary
        parts = body.split(b'--' + boundary)
        for part in parts:
            part = part.strip()
            if not part or part == b'--':
                continue
            # Split headers from content
            if b'\r\n\r\n' in part:
                header_block, content = part.split(b'\r\n\r\n', 1)
            elif b'\n\n' in part:
                header_block, content = part.split(b'\n\n', 1)
            else:
                continue

            # Remove trailing \r\n--
            if content.endswith(b'\r\n'):
                content = content[:-2]

            header_str = header_block.decode('utf-8', errors='replace')
            name_match = re.search(r'name="([^"]+)"', header_str)
            if not name_match:
                continue
            name = name_match.group(1)

            filename_match = re.search(r'filename="([^"]*)"', header_str)
            if filename_match:
                files[name] = (filename_match.group(1), content)
            else:
                fields[name] = content.decode('utf-8', errors='replace')

        return fields, files

    def do_POST(self):
        if self.path == '/api/scan':
            content_type = self.headers.get('Content-Type', '')
            if 'multipart/form-data' not in content_type:
                self._json_response(400, {"success": False, "error": "Expected multipart/form-data"})
                return

            fields, files = self._parse_multipart()

            if 'image' not in files:
                self._json_response(400, {"success": False, "error": "No image uploaded"})
                return

            filename, image_data = files['image']

            # Save uploaded file temporarily
            file_id = str(uuid.uuid4())[:8]
            input_ext = os.path.splitext(filename)[1] or '.png'
            input_path = str(UPLOAD_DIR / f"scan_{file_id}{input_ext}")

            with open(input_path, 'wb') as f:
                f.write(image_data)

            try:
                report = deai.scan_image(input_path, verbose=False)
                self._json_response(200, {
                    "success": True,
                    "report": report,
                })
            except Exception as e:
                self._json_response(500, {"success": False, "error": str(e)})
            finally:
                try:
                    os.unlink(input_path)
                except OSError:
                    pass
            return

        elif self.path == '/api/scan-fix':
            content_type = self.headers.get('Content-Type', '')
            if 'multipart/form-data' not in content_type:
                self._json_response(400, {"success": False, "error": "Expected multipart/form-data"})
                return

            fields, files = self._parse_multipart()

            if 'image' not in files:
                self._json_response(400, {"success": False, "error": "No image uploaded"})
                return

            filename, image_data = files['image']
            file_id = str(uuid.uuid4())[:8]
            input_ext = os.path.splitext(filename)[1] or '.png'
            input_path = str(UPLOAD_DIR / f"input_{file_id}{input_ext}")
            output_path = str(UPLOAD_DIR / f"output_{file_id}.jpg")

            with open(input_path, 'wb') as f:
                f.write(image_data)

            camera = fields.get('camera', 'iphone15')
            base_preset = fields.get('preset', 'medium')
            watermark = fields.get('watermark', None)

            try:
                # Step 1: Scan
                scan_report = deai.scan_image(input_path, verbose=False)

                # Step 2: Build adaptive config targeting high-risk factors
                adaptive_config, overrides, targeted = deai.build_adaptive_config(scan_report, base_preset)

                # Step 3: Process with adaptive config
                report = deai.process_image(
                    input_path, output_path,
                    preset=base_preset,
                    camera=camera,
                    verbose=True,
                    watermark=watermark if watermark else None,
                    config_override=overrides,
                )

                # Step 4: Re-scan output to show improvement
                rescan_report = deai.scan_image(output_path, verbose=False)

                output_id = file_id
                DeAIHandler.outputs[output_id] = output_path

                self._json_response(200, {
                    "success": True,
                    "output_id": output_id,
                    "steps": report["steps"],
                    "preset": report["preset"],
                    "camera": report["camera"],
                    "mode": report.get("mode", "photo"),
                    "scan_before": scan_report,
                    "scan_after": rescan_report,
                    "targeted": targeted,
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._json_response(500, {"success": False, "error": str(e)})
            finally:
                try:
                    os.unlink(input_path)
                except OSError:
                    pass
            return

        elif self.path == '/api/process':
            content_type = self.headers.get('Content-Type', '')
            if 'multipart/form-data' not in content_type:
                self._json_response(400, {"success": False, "error": "Expected multipart/form-data"})
                return

            fields, files = self._parse_multipart()

            if 'image' not in files:
                self._json_response(400, {"success": False, "error": "No image uploaded"})
                return

            filename, image_data = files['image']

            # Save uploaded file
            file_id = str(uuid.uuid4())[:8]
            input_ext = os.path.splitext(filename)[1] or '.png'
            input_path = str(UPLOAD_DIR / f"input_{file_id}{input_ext}")
            output_path = str(UPLOAD_DIR / f"output_{file_id}.jpg")

            with open(input_path, 'wb') as f:
                f.write(image_data)

            # Get params
            preset = fields.get('preset', 'medium')
            camera = fields.get('camera', 'iphone15')
            watermark = fields.get('watermark', None)

            try:
                report = deai.process_image(
                    input_path, output_path,
                    preset=preset,
                    camera=camera,
                    verbose=True,
                    watermark=watermark if watermark else None,
                )

                # Store output for download
                output_id = file_id
                DeAIHandler.outputs[output_id] = output_path

                self._json_response(200, {
                    "success": True,
                    "output_id": output_id,
                    "steps": report["steps"],
                    "preset": report["preset"],
                    "camera": report["camera"],
                    "mode": report.get("mode", "photo"),
                })
            except Exception as e:
                self._json_response(500, {"success": False, "error": str(e)})
            finally:
                # Clean up input
                try:
                    os.unlink(input_path)
                except OSError:
                    pass
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


def main():
    parser = argparse.ArgumentParser(description="DeAI Web Panel")
    parser.add_argument("--port", type=int, default=8890, help="Port (default: 8890)")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    server = HTTPServer(('127.0.0.1', args.port), DeAIHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"DeAI Web Panel running at {url}")
    print(f"Temp dir: {UPLOAD_DIR}")
    print("Press Ctrl+C to stop")

    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()

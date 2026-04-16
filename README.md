# DeAI — AI 图片反检测工具

去除 AI 生成图片的检测特征,让图片通过平台的 AI 内容审核。

## 功能

- **自动分类** — 自动识别照片 vs 插画,选择最优处理策略
- **7 项 AI 检测扫描** — EXIF / 噪点 / 频域 / 色彩 / 压缩 / 锐度 / 隐形水印
- **智能修复** — 扫描后针对高分危险因子自动调参,保护已正常的因子
- **12 层处理 Pipeline** — 传感器噪点 / DoF / 色差 / 暗角 / EXIF 注入 / 厂商量化表等
- **Web 面板** — 拖拽上传、滑动对比、批量处理、ZIP 下载
- **确定性编排** — orchestrator.py 固化所有决策,任何环境结果一致

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 全自动处理 (推荐)
python3 scripts/orchestrator.py auto photo.png

# AI 检测风险扫描
python3 scripts/orchestrator.py scan photo.png

# 启动 Web 面板
python3 scripts/orchestrator.py web
```

## 使用方式

### 全自动模式

```bash
# 单张 — 自动分类 → 扫描 → 智能调参 → 处理 → 验证
python3 scripts/orchestrator.py auto input.png -o output.jpg

# 批量
python3 scripts/orchestrator.py auto ~/ai_images/ -o ~/processed/
```

### 手动指定参数

```bash
python3 scripts/orchestrator.py process input.png --mode photo --preset heavy --camera canon_r5
```

### 查看分类结果

```bash
python3 scripts/orchestrator.py classify input.png
```

## 处理模式

| 模式 | 适用 | 处理策略 |
|------|------|---------|
| photo | AI 仿真人像/风景 | 传感器噪点 + DoF + 色差 + 暗角 + EXIF |
| illustration | 插画/卡通/文字图 | 纸张纹理 + 渐变打断 + 微抖动 |

## 预设

| 预设 | 适用场景 | 自动选择条件 |
|------|---------|-------------|
| light / illust-light | 高质量图微调 | risk < 30% |
| medium / illust-medium | 通用 | 30% <= risk < 60% |
| heavy / illust-heavy | AI 味重的图 | risk >= 60% |

## 相机配置

| ID | 相机 | 场景 |
|----|------|------|
| iphone15 | iPhone 15 Pro Max | 社交媒体 (默认) |
| canon_r5 | Canon EOS R5 | 专业摄影 |
| sony_a7iv | Sony A7 IV | 通用全画幅 |
| nikon_z8 | Nikon Z 8 | 风光摄影 |

## Web 面板

```bash
python3 scripts/orchestrator.py web --port 8890
# 打开 http://127.0.0.1:8890
```

功能:
- 拖拽上传 / 多文件批量
- 模式 / 预设 / 相机选择
- AI 检测风险扫描 (环形仪表盘 + 7 项逐条打分)
- 智能修复 (扫描 → 调参 → 处理 → before/after 对比)
- 滑动对比 / 并排对比
- 单张下载 / ZIP 批量下载

## 架构

```
orchestrator.py          ← 编排层 (唯一入口)
├── classify_image()     ← 图片分类 (color_ratio + flat_ratio + edge_density)
├── select_preset()      ← 预设选择 (基于 risk score)
├── smart_fix()          ← 6 步流程: classify → scan → select → adaptive → process → rescan
│   └── build_adaptive_config()  ← 自适应调参 + 保护模式
├── batch_auto()         ← 批量处理
└── web                  ← Web 面板

deai.py                  ← 处理引擎
├── scan_image()         ← 7 项检测
├── process_image()      ← 12 层 pipeline
├── roughen_histogram()  ← 直方图粗糙化
└── 20+ 处理函数

server.py                ← Web 面板
├── /api/scan            ← 扫描接口
├── /api/process         ← 处理接口
├── /api/scan-fix        ← 智能修复接口
└── 前端 (内嵌 HTML/CSS/JS)
```

## 作为 Claude Code Skill 使用

```bash
# 复制到 skill 目录
cp -r deai/ ~/.claude/skills/deai/

# 然后在 Claude Code 中:
# "帮我处理这张 AI 图" → 自动调用
# "/deai" → 打开面板
```

## 作为 OpenClaw Skill 使用

```bash
# 复制到 workspace skills
cp -r deai/ ~/.openclaw/workspace/skills/deai/
```

## 依赖

- Python 3.9+
- Pillow (图像处理)
- NumPy (数组运算)
- SciPy (FFT / 高斯模糊 / 坐标映射)
- piexif (EXIF 元数据注入)

## License

MIT

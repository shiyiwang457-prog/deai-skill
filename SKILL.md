---
name: deai
description: |
  Remove AI-generated image artifacts to make images look like real camera/hand-drawn output.
  Auto-classifies photo vs illustration, scans AI detection risk, smart-fixes targeting high-risk
  factors, with web panel for visual comparison. Deterministic orchestration — same result on any
  machine.
  Use when asked to "remove AI artifacts", "make it look real", "de-AI", "remove AI flavor",
  "去AI味", "让图片看起来像真实照片", "打开 deai 面板", "deai web", "AI检测", or "反检测".
---

# DeAI — 去除 AI 图片痕迹

所有决策逻辑已固化在 `orchestrator.py`,不依赖 AI agent 的临场判断。

## 依赖

```bash
pip install Pillow numpy scipy piexif
```

## 统一入口: orchestrator.py

所有操作通过 orchestrator.py 的 5 个命令完成,不需要 agent 做任何路由判断:

### 1. auto — 全自动处理 (推荐)

自动分类 → 扫描 → 选预设 → 自适应调参 → 处理 → 二次验证

```bash
# 单张
python3 {SKILL_DIR}/scripts/orchestrator.py auto <图片路径>

# 单张 + 指定输出
python3 {SKILL_DIR}/scripts/orchestrator.py auto <图片路径> -o <输出路径>

# 批量 (自动在原目录创建 deai_output/)
python3 {SKILL_DIR}/scripts/orchestrator.py auto <文件夹>

# 批量 + 指定输出
python3 {SKILL_DIR}/scripts/orchestrator.py auto <文件夹> -o <输出文件夹>
```

auto 命令的 6 步固定流程:
1. `classify_image()` — 自动判断 photo/illustration + 水印检测
2. `scan_image()` — 7 项 AI 检测风险评分
3. `select_preset()` — 根据 risk score 自动选预设 (>=60 heavy, 30-60 medium, <30 light)
4. `build_adaptive_config()` — 针对高分因子 boost 参数,低分因子启用保护模式
5. `process_image()` — 执行处理 pipeline
6. `scan_image()` — 二次验证,输出 before/after 对比

### 2. scan — AI 检测风险扫描

```bash
python3 {SKILL_DIR}/scripts/orchestrator.py scan <图片路径>
python3 {SKILL_DIR}/scripts/orchestrator.py scan <图片路径> --json
python3 {SKILL_DIR}/scripts/orchestrator.py scan <文件夹>
```

### 3. process — 手动指定参数处理

```bash
python3 {SKILL_DIR}/scripts/orchestrator.py process <图片> --mode photo --preset heavy --camera canon_r5
python3 {SKILL_DIR}/scripts/orchestrator.py process <图片> --mode illustration --preset illust-medium
```

不指定 --mode 时自动分类。不指定 --preset 时用 mode 默认值。

### 4. classify — 查看自动分类结果

```bash
python3 {SKILL_DIR}/scripts/orchestrator.py classify <图片路径>
python3 {SKILL_DIR}/scripts/orchestrator.py classify <图片路径> --json
```

输出: mode (photo/illustration) + 水印检测 + 推荐预设 + 分类依据指标

### 5. web — 启动 Web 面板

```bash
python3 {SKILL_DIR}/scripts/orchestrator.py web --port 8890
```

## agent 使用规则

agent 不需要做任何判断,只需要:

1. **用户给了图片路径** → 跑 `orchestrator.py auto <路径>`
2. **用户给了文件夹** → 跑 `orchestrator.py auto <文件夹>`
3. **用户说"扫描/检测"** → 跑 `orchestrator.py scan <路径>`
4. **用户说"打开面板"** → 跑 `orchestrator.py web`
5. **用户指定了具体参数** → 跑 `orchestrator.py process <路径> --mode ... --preset ...`

不要自己判断 photo/illustration,不要自己选 preset,不要自己决定是否加水印去除。orchestrator 全部自动处理。

## 固化的决策逻辑

### 图片分类 (classify_image)
| 指标 | 阈值 | illustration 加分 |
|------|------|------------------|
| color_ratio < 0.15 | 低色彩多样性 | +2 |
| flat_ratio > 0.3 | 大面积平涂 | +2 |
| edge_density < 8 | 低边缘密度 | +1 |
| 总分 >= 3 | → illustration, 否则 photo | |

### 预设选择 (select_preset)
| risk score | photo 预设 | illustration 预设 |
|-----------|-----------|------------------|
| >= 60% | heavy | illust-heavy |
| 30-60% | medium | illust-medium |
| < 30% | light | illust-light |

### 自适应调参 (build_adaptive_config)
- 高分因子 (>50%): boost 对应参数
- 低分因子 (<30%): 禁用该操作 + 保护模式
- 保护模式: 频域 OK → 减弱 CA/distortion/vignette/banding; 色彩 OK → 禁用双重压缩

### 水印检测
- 自动检测四角区域边缘密度
- 检测到 → auto 命令自动加 `--watermark auto`

## 文件结构

```
deai/
├── SKILL.md                    # 本文件 (skill 定义 + agent 指令)
└── scripts/
    ├── orchestrator.py          # 编排层 (所有决策逻辑)
    ├── deai.py                  # 处理引擎 (pipeline + scan + adaptive)
    └── server.py                # Web 面板
```

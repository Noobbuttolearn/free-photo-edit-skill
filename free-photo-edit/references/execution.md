# 跨宿主执行与脚本

本包包含 `SKILL.md`、本页、`scripts/photo_edit.py` 和可选 Codex UI 元数据。WorkBuddy 读取同一份 Markdown 和 Python；不依赖 Codex 的 tools 命名、用户问答面板或本机绝对路径。GLM/DeepSeek 的版本名称不作为图片输出能力的依据。

## 依赖与位置

- Python 3.9+；台账、清理只需标准库。
- 裁切、交付和像素合成：Pillow。
- 本包的 API 生图/编辑适配：openai，使用 OpenAI 兼容 images API；其他 API 使用宿主已有且受支持的工具。
- 不需要 numpy/scipy，不为普通修图搭建前端。

检查当前解释器：`python -c "import sys; print(sys.executable)"`。缺哪个安装哪个，用同一解释器 `python -m pip install Pillow` 或 `python -m pip install openai`。优先项目已有环境；必要时在任务 work 下建 `.venv`，不要修改系统 PATH。Windows 调用 Python 前设置当前进程 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`。UTF-8 文件使用显式编码或 apply_patch。

下文 `SKILL_DIR` 表示当前 skill 目录，按实际所在位置调用，不能原样保留占位字符串。Windows PowerShell 示例变量为 `$photoSkillDir`，勿复用 HOME、CODEX_HOME 等系统变量。

## 1. 建任务与确认计划

需求确认后，将计划写到临时的 UTF-8 JSON。`init` 将其复制进任务台账，之后不要手工改已批准的预算。

```json
{
  "inputs": ["/absolute/path/scene.jpg", "/absolute/path/product.jpg"],
  "preservation": "pixel",
  "final_size": [1080, 1440],
  "bottom_padding_px": 128,
  "max_generations": 3,
  "variants": [
    {"id": "front", "requirement": "坐人一侧朝向镜头", "count": 1},
    {"id": "side", "requirement": "左侧面朝向镜头", "count": 1},
    {"id": "back", "requirement": "靠背背面朝向镜头", "count": 1}
  ]
}
```

`inputs` 必须是存在的文件，避免误把输入放进 scratch。`preservation` 是 `visual` 或 `pixel`。`bottom_padding_px` 必填，使用当前工具实际支持的尺寸；只有用户取消白边时才设为 0。示例尺寸仅用于说明字段，并不意味着每个 API 都支持。`max_generations` 是包括首批、补图、空场景生成在内的总尝试上限；不能小于首批张数。每条 `count` 是合格交付数量，不等于允许无限重生。

```text
python SKILL_DIR/scripts/photo_edit.py init --id chair-views --plan work/plan.json --work-root work/photo-edit --output-root outputs/photo-edit
python SKILL_DIR/scripts/photo_edit.py approve --task work/photo-edit/chair-views/task.json --confirmed
python SKILL_DIR/scripts/photo_edit.py status --task work/photo-edit/chair-views/task.json
```

仅在已有用户确认时执行 `approve --confirmed`。脚本不能替代人的授权。若用户需要改预算/计划，新建一份明确关联旧任务的任务单，先汇总旧任务已消耗次数，再确认剩余新增额度，不能新建任务规避预算或连续失败限制。

## 2A. 宿主原生工具（优先）

先运行准备命令；不产生模型费用，也不消耗生成次数。第一张是实际待编辑底图，之后才是参考图。若底图尺寸不等于确认的最终内容尺寸，先解决任务尺寸，不能静默缩放。

```text
python SKILL_DIR/scripts/photo_edit.py prepare --task work/photo-edit/chair-views/task.json --variant front --prompt-file work/front-prompt.txt --image /path/to/scene.png --image /path/to/product.jpg
python SKILL_DIR/scripts/photo_edit.py reserve --task work/photo-edit/chair-views/task.json --variant front --method native --prepared PREPARATION_ID
```

`prepare` 返回准备 ID、`prompt_file`、`images`、`mask` 和 `canvas_size`。提示词已自动加入白边布局；`images[0]` 是生成前加白边的底图，其他参考图未改变。向原生生图工具传入该文件里的完整提示词、该 images 列表以及完整 canvas_size；不要回退为用户短句和原始无白边底图。有蒙版可给 `prepare --mask`，只接受匹配未加白边底图的 alpha PNG，脚本会同步扩展并保护白边。

每次调用原生工具前预留一张。`reserve` 返回 attempt ID；有白边却没有有效准备 ID，或准备后的提示词/图像已改变时，脚本拒绝预留。额度或连续失败限制拒绝时也不再调用工具。

给工具一张图的请求，返回后直接登记，脚本会将原始结果复制到 scratch 并立刻验白边。无需先手工复制，也不要在图片生成后额外加白边。

```text
python SKILL_DIR/scripts/photo_edit.py record --task work/photo-edit/chair-views/task.json --attempt ATTEMPT_ID --image /path/to/tool-returned.png
```

工具失败：`record --attempt ATTEMPT_ID --failed --reason api-error`。图生成成功但朝向错误等，检查后用 `reject --attempt ATTEMPT_ID --reason wrong-facing`。同一个 variant 最后连续两次被标记相同失败原因时，脚本禁止该 variant 再预留；应改用不生成的新合成方案，或与用户另行明确讨论任务修改。单纯换提示词/模型不算解决原因。

`record` 检测到无白边时返回非零退出码和 `reason: missing-bottom-padding`，将该次尝试标为 failed，保留原始图片；不能忽略错误继续裁切或交付。尺寸不对返回 `wrong-canvas-size`。这次尝试仍然消耗额度，不会自动补图。

原生工具无法输出单张时，必须事先在台账逐张预留实际会生成的数量。不能只登记要交付的图而隐藏失败输出。

## 2B. 图片 API 适配

密钥和服务商 URL 通过当前进程环境 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 传入。base URL 指向兼容 API 根（通常以 `/v1` 结尾），不写入任务单。不要打印配置或把 key 放命令参数。用户已指定自定义服务商时，按其实际模型和接口能力使用；模型出现在列表中还需验证编辑能力。

```text
python SKILL_DIR/scripts/photo_edit.py api --task work/photo-edit/chair-views/task.json --variant front --model gpt-image-2 --prompt-file work/front-prompt.txt --image /path/to/scene.png --image /path/to/product.jpg --mask /path/to/api-mask.png --size auto --quality high
```

无 `--image` 为生成，有 `--image` 为编辑。API 命令自动调用相同的准备步骤，将底图提前加白边、注入具体布局提示词并传入完整画布尺寸。`--size auto` 在启用白边时会解析为任务单的 `W x (H+B)`；显式尺寸不匹配则在调用前报错。接口不支持该尺寸时，应在调用前选择受支持尺寸/工具，不把白边关闭来适配。

API 蒙版是带 alpha 的 PNG，透明区允许改动；本地交付合成的 edit-mask 则是灰度白色允许编辑、黑色保留。二者方向不同，不能直接混用。传给 API 命令的 mask 必须匹配未加白边第一张图尺寸，并实际有透明区域；脚本同步扩展。某模型不支持的 size/quality/mask 根据服务商错误处理，不在失败后偷偷切模型或重发。

脚本每次预留 1 张，SDK `max_retries=0`。成功返回 base64 图片时写 scratch 并检查完整尺寸和白边，检查通过才进入 review；不通过则 failed 且命令退出码非零。只有 URL、异常结构或超时时留在 failed 状态，由用户选定工具核实服务端结果。异常只输出简要类型/状态码，完整返回体不落盘。不会自动下载任意图片 URL。

## 3. 看图、裁白边与交付

可以独立运行 `python SKILL_DIR/scripts/photo_edit.py check --task work/photo-edit/chair-views/task.json --image /path/to/result.png`；无白边或尺寸错误返回非零退出码。

先实际检查生成图，合格才运行 `deliver`。`deliver` 要求 `--reviewed` 表示已经看过；脚本本身不具备视觉判断能力，不能把该开关当成免检。

```text
python SKILL_DIR/scripts/photo_edit.py deliver --task work/photo-edit/chair-views/task.json --variant front --candidate work/photo-edit/chair-views/scratch/ATTEMPT_ID.png --attempt ATTEMPT_ID --reviewed
```

根据计划要求检查 `W × (H+B)`，白边至少 90% 接近白色才允许裁切。白边高固定为已确认的 B，不能自动加大，也不能单靠白色比例声称主体没被剪。输出一律 PNG。

保留模式是 pixel 时，需要原图与编辑区蒙版：

```text
python SKILL_DIR/scripts/photo_edit.py deliver --task work/photo-edit/chair-views/task.json --variant front --candidate /path/to/reviewed.png --original /path/to/scene.png --edit-mask /path/to/white-edit-black-keep.png --attempt ATTEMPT_ID --reviewed
```

`original` 和 `edit-mask` 的尺寸必须为最终 `W × H`。先裁白边，再以蒙版合成；黑色区逐像素验证不变。候选尺寸不符直接报错，不自动拉伸。可以使用已登记输入的原图进行纯本地合成，不传 `--attempt` 时 `--source-note` 必填，说明素材与操作；本地操作不增加生成次数。由其他工具生成的图片必须先登记 attempt，不能冒充本地素材绕过额度。

如果需要纯裁切，可运行 `crop --image ... --out ... --bottom B --expected-width W --expected-height H --reviewed`。先看图，白边校验不通过就停，不能关闭检查后强裁。

## 4. 收口

```text
python SKILL_DIR/scripts/photo_edit.py cleanup --task work/photo-edit/chair-views/task.json
python SKILL_DIR/scripts/photo_edit.py cleanup --task work/photo-edit/chair-views/task.json --apply
```

全部交付完成才允许清理。清理范围是脚本登记过且内容未变的 scratch 普通文件。若要登记自己制作的临时蒙版/合成文件，使用 `track --task ... --file ...`，文件必须已位于本轮 scratch，且不是登记输入。不要把原图复制进 scratch 再登记为可删除临时文件。未知文件、修改过的文件、符号链接保留并报告；不会清理其他工具的缓存或 Python 环境。

安装后 skill 的通用脚本留在 skill 内，最终图留在输出目录，任务台账保留以便查看实际尝试。用户要求保留过程素材时，不执行清理。

## 安装和能力边界

可将整个 `free-photo-edit` 文件夹复制到宿主的用户技能目录。例如 Codex 常用 `~/.codex/skills/`，本机 WorkBuddy 已验证扫描 `~/.workbuddy/skills/` 下的 `SKILL.md`。另一台机器优先使用其导入功能或实际发现路径，不能假设固定 Windows 用户名。刷新技能列表/重开会话后用“使用 free-photo-edit 帮我 P 图”调用。

宿主有无原生图片工具、GLM/DeepSeek 实际视觉输入能力、API 套餐和计费分别取决于环境。脚本离线验证不代表已经端到端验证了每个宿主模型；不得宣称所有模型天然支持看图或生图。

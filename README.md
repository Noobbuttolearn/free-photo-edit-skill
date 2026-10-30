# 自由 P 图 / free-photo-edit

把原图和参考图交给 AI 助手，先明确修改目标、保留项和张数，再调用可用图片工具完成修图、检查细节与整理交付。

适用于家具替换、局部改色、换装、多图合成和多个明确版本的图片编辑任务。可由 WorkBuddy、Codex 等能读取技能说明、操作文件并调用图片工具的宿主使用。

> “链接安装”与 GLM-5.3-Flash 的完整修图链路尚未端到端验证。已有脚本和安装说明不等于所有宿主均已实测通过。

采用 [MIT 许可](LICENSE)，允许使用、修改和商用，分发时保留许可声明。

[GitHub 主仓库](https://github.com/Noobbuttolearn/free-photo-edit-skill) · [Gitee 镜像](https://gitee.com/user-zhou/free-photo-edit-skill)（同步中，以 GitHub 为准）

[下载完整技能 ZIP](free-photo-edit-v2.zip) · [复制 WorkBuddy 安装话术](INSTALL-IN-WORKBUDDY.md) · [SHA-256 校验](SHA256SUMS.txt)

两个平台按相同版本和校验值同步，具体约定见 [MIRRORING.md](MIRRORING.md)。

## 获取与安装

推荐提供固定版本 ZIP。当前 ZIP 文件名为 `free-photo-edit-v2.zip`，内含完整的 `free-photo-edit/` 目录。

### WorkBuddy 官方导入入口

1. 从 https://www.workbuddy.cn/ 下载并安装 WorkBuddy，完成登录。
2. 下载本仓库提供的 [完整技能 ZIP](free-photo-edit-v2.zip)。
3. 打开 **专家·技能·连接器 → 技能 → 添加技能 → 上传技能**，选择 ZIP。
4. 在“已安装”中检查自由 P 图 / free-photo-edit 是否已启用；必要时新建会话后调用。
5. 先检查当前环境是否具备图片读取、图片编辑工具与所需 Python 依赖，再开始修图。

官方技能文档：https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market

WorkBuddy 官方说明中的“对话安装”仅支持技能市场中的技能。让助手从 GitHub 链接获取并安装自定义 Skill，是需要按具体版本实测的文件安装流程，不是官方对任意链接的保证。

### 手动目录安装

根据当前 WorkBuddy 实际扫描目录放置完整文件夹。本机已验证存在 `~/.workbuddy/skills/free-photo-edit/SKILL.md`；其他版本优先使用官方导入入口或检查实际目录，不硬编码 Windows 用户名。

```text
free-photo-edit/
├── SKILL.md
├── agents/openai.yaml
├── references/execution.md
└── scripts/photo_edit.py
```

不要只复制 SKILL.md，也不要覆盖已经安装且用途未确认的同名版本。

## 开始使用

将场景图与参考图附在同一任务中，说明各自用途：

> 使用 free-photo-edit。第一张是要修改的原图，第二张是物体参考图。把原图里的两把椅子换成参考款，保持自然的透视与光照，桌子和背景尽量保留。先检查你是否能读取图片以及有哪些图片编辑工具，再确认修改范围。只生成 1 张，额外尝试先问我，原图不要覆盖。

主控模型负责理解与调度，图片输出依赖宿主原生工具、MCP 或已配置的图片 API。装好 Skill 不等于自动获得图片模型、API 凭据、免费额度或视觉能力。

GLM-5.3-Flash 是 WorkBuddy 内置模型之一；截至 2026-10-30，官方模型表只为它标注思考模式。不能仅凭模型名称承诺它可直接看图或生图；需检查实际工具链。

## 依赖与行为

Python 3.9+；台账主要使用标准库。裁切与本地合成需要 Pillow；通过内置 OpenAI 兼容 API 脚本出图时才需要 openai 与相应服务。按实际缺失补装，不要求初学者预先配置全部服务。

Skill 会先明确输入角色、范围和数量，控制生成尝试；默认白边与尺寸需要在生成前确认。局部编辑若要求区域外像素一致，需本地合成与差异检查。完整执行说明见 [references/execution.md](free-photo-edit/references/execution.md)。

原图保持只读。生成结果的质量、时间、额度和费用取决于所用宿主与图片服务；不保证所有宿主和模型均已通过端到端测试。

## 许可与验证状态

- MIT 许可已由作者确认，根目录和 ZIP 内均保留许可文本。
- 网址安装与目标模型的图片读取 / 调度、图片工具和依赖仍需按当前 WorkBuddy 版本实测。
- 发布包只含技能及许可文件，不含案例照片、任务台账、密钥或账号配置。

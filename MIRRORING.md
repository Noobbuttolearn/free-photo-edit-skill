# GitHub 主仓库与 Gitee 镜像

发布架构已由作者确认：GitHub 为主，Gitee 为镜像，采用 MIT 许可。

仓库地址：

- GitHub：`https://github.com/Noobbuttolearn/free-photo-edit-skill`
- Gitee：`https://gitee.com/user-zhou/free-photo-edit-skill`

GitHub 是修改与版本发布的来源；Gitee 同步同一 `main` 提交与版本标签。ZIP 本身纳入仓库，两个平台可校验同一个 SHA-256。当前直接从仓库提供 ZIP；若另外创建 GitHub Release，使用相同 ZIP 与 `SHA256SUMS.txt`。

首次发布需使用空的新仓库。作者提供的 `user-zhou/built-casually` 已有麦克纳姆轮小车项目，不作为 Skill 的同步目标；不得用强制推送或整仓镜像覆盖它。

本地配置好实际远端后，使用普通推送同步：

```sh
git push origin main
git push gitee main
git push origin refs/tags/v2.1.0
git push gitee refs/tags/v2.1.0
```

如果远端有不相关历史、受保护分支或拒绝快进，应检查差异后处理，不使用 `--force`、`--mirror` 或删除远端引用。

更新流程：只修改主仓库内容 → 检查核心文件与 ZIP → 更新校验文件 → 提交 → 创建新版本标签 → 普通推送两个远端 → 验证双方提交和下载文件一致。

当前发布为 `v2.1.0`，技能包为 `free-photo-edit-v2.1.0.zip`。旧 `v2.0.0` 标签和 `free-photo-edit-v2.zip` 保留原内容；升级时新增版本包，不覆盖历史包。`SHA256SUMS.txt` 同时保留两份 ZIP 的校验值。

镜像地址可以交给国内观众；若未同步完成，应明确标注，不以旧版本冒充最新版本。

# GitHub 主仓库与 Gitee 镜像

发布架构已由作者确认：GitHub 为主，Gitee 为镜像，采用 MIT 许可。

规划地址（发布前不可当作已上线资源）：

- GitHub：`https://github.com/Noobbuttolearn/free-photo-edit`
- Gitee：`https://gitee.com/user-zhou/free-photo-edit`

GitHub 是修改与版本发布的来源；Gitee 同步同一 `main` 提交与版本标签。ZIP 本身纳入仓库，两个平台可校验同一个 SHA-256。发布 GitHub Release 时，附上同一个 ZIP 与 `SHA256SUMS.txt`。

首次发布需使用空的新仓库。作者提供的 `user-zhou/built-casually` 已有麦克纳姆轮小车项目，不作为 Skill 的同步目标；不得用强制推送或整仓镜像覆盖它。

本地配置好实际远端后，使用普通推送同步：

```sh
git push origin main
git push gitee main
git push origin refs/tags/v2.0.0
git push gitee refs/tags/v2.0.0
```

如果远端有不相关历史、受保护分支或拒绝快进，应检查差异后处理，不使用 `--force`、`--mirror` 或删除远端引用。

更新流程：只修改主仓库内容 → 检查核心文件与 ZIP → 更新校验文件 → 提交 → 创建新版本标签 → 普通推送两个远端 → 验证双方提交和下载文件一致。

镜像地址可以交给国内观众；若未同步完成，应明确标注，不以旧版本冒充最新版本。

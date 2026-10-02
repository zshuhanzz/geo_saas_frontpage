# Cloud Scheduler 原地更新修复设计

## 目标

Admin UI 修改 Workspace 的 cron 表达式时，必须更新已存在的 Cloud Scheduler Job，不得为了名称迁移创建新 Job 再删除旧 Job。

## 行为规则

1. 若经过 Workspace 完整身份校验的旧短名 Job 存在，原地更新该 Job。
2. 否则，若全 UUID Job 存在，原地更新该 Job。
3. 仅当两种 Job 都不存在时，创建全 UUID Job。
4. 普通 cron 更新不迁移、不删除任何已有 Job。
5. 清空 cron 时只删除当前可操作的单个已验证 Job；Workspace 最终删除仍由严格删除服务处理。
6. 同步 Cloud Scheduler Python SDK 调用不得阻塞 FastAPI 事件循环。

## 兼容性与安全

- 旧短名 Job 必须继续通过 description 与 HTTP target 中完整 client_id 双重校验，避免 UUID 前八位碰撞造成跨 Workspace 操作。
- 已存在但归属不匹配的旧任务不得更新或删除；此时按“旧任务不可用”处理，并使用该 Workspace 的全 UUID Job。
- Cloud Scheduler 控制面异常只影响后台同步结果，不得阻塞 Admin API 的其他请求。

## 验证

- 旧短名任务存在时：调用 UpdateJob，零次 CreateJob，零次 DeleteJob。
- 仅全 UUID 任务存在时：原地 UpdateJob。
- 两者都不存在时：创建全 UUID Job。
- 旧短名身份不匹配时：绝不修改它。


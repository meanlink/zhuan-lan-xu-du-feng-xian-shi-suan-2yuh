# 专栏续读风险试算

分类与阈值选择的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
四个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、BlindCase 盲评案件、Report 分发计划；辅助 User、Audit、Delivery。

### 盲评专用批次（防止留出成绩调参高估）
反复查看同一留出集再调参会让续读预测看起来更好。负责人导入盲评批次时，系统按读者一次性固定 75% 开发集 / 25% 封存集，并落成三个受控批次（盲评全量、开发集、封存集）：

- **立案**：仅负责人可建案；同一读者不得进入第二个盲评案，避免标签在别处被再次看到。
- **开发**：分析员和负责人可新增候选试验，候选只能绑定本案开发集；封存集的记录与标签不出现在普通批次列表、详情或普通分析入口。
- **选定**：仅负责人可选定已完成候选；选定即一次性锁定标准化参数、系数和阈值；一案只接纳一次选择，并发选择由条件更新保证只接受先落定者。
- **开封**：锁定后自动生成封存集一次性开封任务，只评分不重新训练、不重新抽人；开封失败保留“开封中/待恢复”，重试沿用同一任务、锁定成果与原分组，不新增评估。
- **落定**：开封结果完整落定后案件才转为已完成，才可读取明细、批准并用于简报；候选试验不能单独批准或分发。
- **页面**：`#/blind` 立案、按开发中/已锁定/开封中/已完成分组查看台账与来源；`#/blind/{id}` 新增候选、查看候选开发集结果、选定、恢复开封、批准开封结果。既有普通批次与试验全部保留。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18207；后端文档 http://localhost:19207/docs；数据库宿主端口 17707。盲评入口在左侧“盲评专用批次”。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、读取与下载|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准或安排分发|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；MySQL 8.0；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=reader-risk；FRONTEND_PORT=18207；BACKEND_PORT=19207；DB_PORT=17707；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1008/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。

# PDF Analysis 使用说明

本服务将 PDF 解析能力封装为 MCP 服务器，内部只保留一条共享流水线，多个请求会自动排队，避免并发启动多个解析器导致内存占用过高。启动前请先进入 `pdf_analysis/` 目录并执行 `uv sync` 安装依赖。HTTP 模式使用 `uv run main.py http --host 127.0.0.1 --port 8001` 启动，stdio 模式使用 `uv run main.py stdio` 启动。服务启动后不会立即加载 Docling converter，而是在第一个任务真正执行时再初始化，因此首个任务会比后续任务稍慢。

调用时优先使用 `submit_pdf_parse` 提交任务，传入 `input_path`，可选传入 `output_dir` 和 `timeout_seconds`。工具会立即返回 `job_id`，不会阻塞等待解析完成。随后使用 `get_parse_job` 查询状态，可能的状态包括 `queued`、`running`、`succeeded`、`failed`、`cancelled`。使用 `list_parse_jobs` 可查看最近任务，使用 `cancel_parse_job` 可取消尚未开始的排队任务，`get_server_status` 可查看当前队列长度和流水线是否已预热。若未指定输出目录，结果默认写入 `jobs/<job_id>/output/`。
# PDF Analysis MCP

一个用于解析论文 PDF 的 MCP 服务器。

它把 PDF 转成适合 AI 消费的结构化输出，并通过单条流水线串行处理任务，避免并发请求把机器资源打满。

## 适用场景

- 解析单个论文 PDF
- 批量解析目录下的多个 PDF
- 从 PDF 中提取正文、章节、图片、表格和摘要信息
- 让 AI 先提交任务，再按 `job_id` 轮询结果

## 工作方式

- 全局只有 1 条解析流水线
- 所有请求先进队列
- 工具调用立即返回 `job_id`
- 使用 `get_parse_job` 查询状态和结果
- 任务状态仅保存在内存中，服务重启后会丢失

## 启动

HTTP:

```bash
uv run main.py http --host 127.0.0.1 --port 8001
```

stdio:

```bash
uv run main.py stdio
```

## MCP Tools

### `submit_pdf_parse`

提交一个 PDF 解析任务。

参数：

- `input_path`: PDF 文件路径，或包含多个 PDF 的目录路径
- `output_dir`: 可选，输出目录
- `timeout_seconds`: 可选，单文档超时秒数，默认 `500.0`

返回：

- `job_id`
- `status`
- `queue_position`
- `output_dir`

### `get_parse_job`

查询任务状态或结果。

参数：

- `job_id`

返回字段包含：

- `status`: `queued` / `running` / `succeeded` / `failed` / `cancelled`
- `submitted_at`
- `started_at`
- `finished_at`
- `error`
- `result`

### `list_parse_jobs`

列出已知任务。

参数：

- `status`: 可选状态过滤
- `limit`: 返回数量上限

### `cancel_parse_job`

取消一个排队中的任务。

参数：

- `job_id`

说明：

- 只能取消 `queued` 任务
- `running` 任务不会被强制中断

### `get_server_status`

获取服务器当前状态。

返回字段包含：

- `pipeline_count`
- `worker_started`
- `converter_ready`
- `running_job_id`
- `queued_jobs`
- `total_jobs`
- `queue_max_size`

## 输出内容

每篇论文会输出一组结构化文件，通常包括：

- `summary.json`
- `manifest.json`
- `paper_body.md`
- `abstract.md`
- `references.md`
- `sections/`
- `figures/`
- `tables/`

## 推荐给 AI 的调用方式

1. 先调用 `submit_pdf_parse`
2. 记录返回的 `job_id`
3. 周期性调用 `get_parse_job`
4. 当 `status == "succeeded"` 时读取 `result` 和输出目录中的文件
5. 当 `status == "failed"` 时读取 `error`

## 注意事项

- 首个真正执行的任务会触发 converter 懒加载，可能更慢
- 默认输出目录为 `pdf_analysis/jobs/<job_id>/output`
- 如果传入自定义 `output_dir`，调用方应自行避免路径冲突

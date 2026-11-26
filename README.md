# 电影资料馆声带修复审听与放映服务

片库提供数字化的单声道声带，剪辑师去除坏拍并调整各段音量，审听员核听固定修复稿，放映员按发行号领取对应的 WAV 和剪辑单。服务使用 Python 3.11 标准库，监听本机回环地址。

## 运行

```sh
python3 -B -m releases.service --db restoration.sqlite --port 8080
python3 -B check_project.py
python3 -B demo.py
```

新工作区默认 8000 Hz，可用 `--sample-rate` 选择首次建库的采样率。重开时省略该参数会继续使用库内采样率。指定不同采样率会拒绝启动。临时块默认每块 1024 帧，可用 `--block-frames` 调整。启动只初始化表，重复启动保留已提交的业务记录。演示读取 `examples/restoration.json`，在独立临时工作区通过真实 HTTP 运行，退出时清理临时目录。

## 一个班次的接口

所有请求和响应均为 JSON。素材、修订、试听和发行使用数值 ID，确认号是 `confirm-` 开头的字符串。帧从 0 起计，一帧为一个样本。所有窗口均左闭右开。

| 步骤 | 接口 | 请求及结果 |
| --- | --- | --- |
| 1. 登记原件 | `POST /assets` | `{"source":"片库卷一","sample_rate":8000,"samples":[1,2,3]}`。返回 `asset_id`、`source`、`sample_rate` 和 `frames`。 |
| 2. 冻结修复稿 | `POST /cuts` | `{"project_id":"film-1","segments":[{"asset_id":1,"start":1,"end":3,"gain":2}]}`。后继稿另传 `parent_revision_id`。返回 `revision_id`、`project_id`、`parent_revision_id`、`total_frames` 和有序 `segments`。 |
| 3. 预览 | `GET /cuts/1/preview?start=0&end=2` | 返回 `revision_id`、`window` 和 `samples`，示例为 `[4,6]`。省略端点时分别使用 0 和版末。 |
| 4. 打开试听 | `POST /auditions` | `{"revision_id":1}`。返回试听号 `audition_id`、固定修订和初始进度。 |
| 5. 推进与回听 | `POST /auditions/1/transport` | `{"op":"advance","frames":1}`、`{"op":"seek","position":0}` 或 `{"op":"pause"}`。返回 `position`、`paused`、`output_window`、`samples`、`heard`、`pending` 和固定会话身份。推进可从暂停继续。 |
| 6. 确认 | `POST /auditions/1/confirm` | 传空对象或空请求体。会话已听齐时返回 `confirmation_id`、`revision_id` 和 `audition_id`。 |
| 7. 发放 | `POST /releases` | `{"revision_id":1,"confirmation_id":"confirm-1"}`。同版确认及成品提交成功后返回 `release_id` 和 `revision_id`。 |
| 8. 领取 | `GET /releases/1` | 返回上述身份、`confirmation_id`、`cue_sheet` 和 `wav_base64`。重启后可用原号领取。 |

每个剪辑单片段包含 `segment_id`、从 0 开始的 `ordinal`、`asset_id`、`source_window`、`gain` 和 `output_window`。重复引用保留各自实例。同一修订内的片段连续拼接，出样先乘整数增益，再饱和到 `[-32768,32767]`。WAV 为固定采样率、单声道、有符号 16 位小端 PCM。

空素材、PCM 非整数或越界、采样率不符、非法源窗或控制参数返回 400。未知会话、修订或发行号返回 404，作为冻结参数的未知父版或素材返回 400。错项目父版、欠听或缺少同版确认返回 409。暂停和定位不输出音样，跳过的范围仍待听。试听缺块时补位为零，补位窗仍待听，真实素材零可以计入进度。预览及发行需要完整渲染，缺块返回 503。发行提交失败返回 500，已有交付件仍可领取。错误响应含 `error` 字段。

完整回归从 `tests` 包发现，沿 HTTP 核对源窗、增益饱和、重排、块归属、欠听回补、同版资格、WAV 和剪辑单，并用 SQLite 延迟约束实际触发一次提交失败。运行夹具通过 `server.cache.defer_once(revision_id, block_start, block_end)` 模拟一次取块不可用，通过 `server.cache.reclaim()` 回收临时块。块边界是从 0 按块长分割的固定输出窗，末块截于版末。两项操作均可从嵌入服务的测试或维护代码调用。

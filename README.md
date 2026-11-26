# 青榆展馆校声服务

厅内校声员登记布线和参考短样，再以实际增益复听。远端调音员预览、发令并按原号查单。下一班用固定复盘核对实际调节次序和各次前后值。

## 运行

需要 Python 3.11，无第三方依赖。在项目根目录运行完整回归和班次演示。

```sh
python3 -B check_project.py
python3 -B demo.py
```

`check_project.py` 由运行平台提供。直接运行标准库套件可用 `python3 -B -m unittest discover`。演示在临时目录启动台端和厅端，实际走 HTTP，重启两个服务后再领取复盘。日常运行时可分别启动以下服务，并在重启时使用原数据库路径。

```sh
python3 -B -m session.service --db room.sqlite3 --port 8101
python3 -B -m desk.service --db desk.sqlite3 --port 8100 --room-port 8101
```

两个独立 SQLite 文件分别保存厅端和台端状态。监听地址均为 `127.0.0.1`。启动时打印实际端口，`--port 0` 可自动分配端口。结构初始化可重复执行，保留登记的线路、用户样本、实际增益、原单和复盘。业务客户端使用台端端口。厅端的 `/_room/` 路由供台端使用。

## JSON HTTP

POST 请求正文为 JSON 对象。GET 请求使用表中参数名。标识是非空、首尾无空白的区分大小写字符串。成功的读取或提交返回 HTTP 200。请求格式错误返回 400，资源不存在返回 404，身份冲突、已关场及未结收场返回 409，缺样和预览量程不足返回 422，台厅连接不可用时可能返回 503。普通错误正文含 `error`，缺样还指出声道，布线校验可附原因。提交已受理但结局尚未核实时返回 200 和 `status: pending`。

| 调用 | 参数 | 结果 |
| --- | --- | --- |
| `POST /open` | `hall`、`sources`、`wiring`、`initial` | `hall`、`status: open`、`levels` |
| `POST /sample` | `hall`、`channel`、`sample_id`、`frames` | 已绑定的厅场、声道和样本号 |
| `POST /listen` | `hall`、`samples`（声道到样本号的映射） | `hall`、实时快照 `levels` 和逐帧 `mix` |
| `POST /preview` | `hall`、`change` | `hall`、两路 `before` 和拟调 `after`，无写入 |
| `POST /submit` | `hall`、`request_id`、`change` | 待查、成功首执或正式拒绝 |
| `GET /request` | `hall`、`request_id` | 待查或原终局，可查实已有首执 |
| `POST /manual` | `hall`、`operation_id`、`channel`、`gain` | 实际前后值、现场身份和实调序次 |
| `POST /close` | `hall` | `hall`、`status: closed`、`report_id` |
| `GET /report` | `hall`、`report_id` | 固定复盘及按实际序次排列的 `operations` |

开场示例。按 `wiring` 条目声明至少两路，每个声道唯一，来源须在 `sources` 登记。`initial` 必须恰好覆盖布线声道。

```json
{"hall":"qingyu","sources":["feed-L","feed-R"],"wiring":[{"channel":"L","source":"feed-L"},{"channel":"R","source":"feed-R"}],"initial":{"L":6,"R":4}}
```

给 L、R 分别登记 `sample_id` 为 `unit` 且 `frames` 为 `[1]` 的短样，试听正文为 `{"hall":"qingyu","samples":{"L":"unit","R":"unit"}}`。两路的同名短样独立保存。再次登记同一厅场、声道和样本号可更新对应短样。短样元素必须为整数，空数组可登记，但选中时与未绑定一样报 `missing_sample`。试听使用全部登记声道。增益以 0 至 10 的整数格表示，混声为整数样本幅值乘增益格数后的精确和。左、右短样分别为 `[1,-2,3]`、`[2,1]` 时，增益 `(6,4)` 产生 `[14,-8,18]`。较短非空声道的尾部按零处理。

`change` 有两种形式，两个声道必须不同，目标格数或转拨格数须为 0 至 10 的整数。

```json
{"kind":"set","source":"L","target":"R","source_gain":4,"target_gain":6}
```

```json
{"kind":"transfer","source":"L","target":"R","steps":2}
```

固定设值按原目标办理。转拨在厅端首次受理时从实际源声道减去指定格数，并给实际目标声道加上同样格数。任一路越界，整笔返回 `status: rejected` 和 `reason: range_exceeded`。正式拒绝是可复领的终局。成功首执含 `hall`、`request_id`、`change`、`status: applied`、`sequence` 和本次两路实际 `before`、`after`。厅场内同号同参可续办或领回首执，同号异参返回 `parameter_conflict`。查单可以登记核实的结局，查询本身不发令。试听给出查询时实际值，当次结果以首执为准。

现场只修改指定声道，回执保留全厅实际前后值。现场操作号与远端请求号各有自己的命名空间。现场重领原成功回执可跨收场，同号异参仍拒绝。收场前请查完待查单。有关联待查时，`/close` 返回 `pending_requests`，厅场保持开放。收场后仍能试听、查单和领报，新实调返回 `closed_session`。重复收场返回原复盘号。报告仅收录产生实际操作的终局，按 `sequence` 排列，`origin` 区分 `remote` 和 `manual`。

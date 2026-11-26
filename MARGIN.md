# 双声道限额调音

## 开场与试听

沿用 README.md 的台端 `POST /open`，可选传入 `margin` 对象。限额场次恰有两路，`local_channel` 和 `remote_channel` 分别引用两个不同的已布线声道。`limit` 为 1 至 10 的整数，原有单路量程照用，初始合计不得超过 `limit`。开场时全部未用额度归厅端。成功沿用原开场响应。省略 `margin` 即为普通场次，继续使用全部原接口。限额场次仍可载样和试听，试听给出当时的实际增益和混声。限额场次的旧 `/submit`、`/manual` 及其厅端执行路径须拒绝产生实调或待办，以免绕过已划额度。

```json
{"hall":"matinee","sources":["feed-L","feed-R"],"wiring":[{"channel":"L","source":"feed-L"},{"channel":"R","source":"feed-R"}],"initial":{"L":3,"R":3},"margin":{"limit":10,"local_channel":"L","remote_channel":"R"}}
```

## 发额、现场调节与远端承诺

| HTTP | 服务 | JSON 参数 |
| --- | --- | --- |
| `POST /margin/grant` | 台端 | `hall`、`grant_id`、`steps` |
| `POST /margin/local` | 厅端直连 | `hall`、`operation_id`、`gain` |
| `POST /margin/raise` | 台端 | `hall`、`request_id`、`steps` |
| `GET /request` | 台端 | 查询参数 `hall`、`request_id` |
| `POST /close` | 台端 | `hall` |
| `GET /report` | 台端 | 查询参数 `hall`、`report_id` |

`steps` 为正整数。`gain` 为 0 至 10 的整数。标识和一般错误沿用 README.md。台端和厅端使用各自的数据库，沿现有受信环回 HTTP 链路交换业务消息。内部消息格式由实现确定。

**发额。** 台端向厅端申请 `steps` 格。厅端成功划出即从现场可用余量中扣除。尚未兑现的已划额度继续占用余量，即使台端尚未收到回证。可用余量不足返回 HTTP 422，未划出额度。成功的公开回执为 `{"hall":"matinee","grant_id":"G1","steps":2,"status":"granted"}`。失答未核实时返回同样的身份和 `steps`，状态为 `pending`。原参重投同一路径续办或复领。台端只凭可核对的厅端发额证据增加可承诺额度。已取得的证据可以同时证实多笔发额。前一笔回证缺失或在途时，独立的新发额仍须能够完成。重复回证只能证实同一份权利。

**现场调节。** `gain` 是现场声道的目标绝对值。厅端按实值和已划未兑现额度校验。现场有余量即可独立办理，超限返回 HTTP 422，保持原实值和历史。现场降档释放的余量可重新用于现场或发额。成功回执沿用原现场实调形状，含 `hall`、`operation_id`、`channel`、`gain`、`status: applied`、`before`、`after` 和 `sequence`，`channel` 为开场声明的现场声道。

**远端承诺。** `steps` 是远端声道在厅端实际兑现时要增加的格数。台端已证实且未支用的额度足够时须受理，即使台厅断链。额度不足返回 HTTP 422，不占请求号。承诺已持久受理而尚未核实时，返回 `{"hall":"matinee","request_id":"R1","steps":2,"status":"pending"}`。原参重投 `/margin/raise` 可续送或复领。各承诺可分别续送，厅端按实际落地顺序记序，迟到的已承诺原单仍须兑现。每单只改变一次实值，合计始终在上限内。成功返回 `hall`、`request_id`、`steps`、`status: applied`、两路实际 `before` 和 `after` 以及 `sequence`。首执固定，后续现场调节不改变它。`GET /request` 可以确认已经发生的实调，查询不能触发实调。

发额、现场操作和已承诺请求在各自的厅场内按原号同参续办或复领，服务重开后照常。同号异参返回 HTTP 409。普通场次调用限额入口，或限额场次调用旧实调入口，返回 HTTP 409。可沿用现有错误正文和资源不存在约定。

## 收场

有已承诺但尚未核实实调的请求时，`/close` 返回 HTTP 409 `pending_requests`。结清后，开始向厅端办理关闭前，台端必须持久停止新的承诺受理。收场请求或应答丢失后，重开可用同一 `hall` 续办。迟到的发额回证不能恢复接单，未支用的额度及发额本身不阻挡收场。沿原号领取已完成的首执和复盘。`/report` 保留原形状，按 `sequence` 返回实际调节，`origin` 区分现场与远端。发额和承诺受理本身不列作实调。

## 演练

1. 用上面的开场请求，给 L、R 各载入 `unit: [1]`。发额 `{"hall":"matinee","grant_id":"G1","steps":2}`。切断台厅通信后，台端受理 `{"hall":"matinee","request_id":"R1","steps":2}`，厅端办理 `{"hall":"matinee","operation_id":"L5","gain":5}`。随后现场请求 6 格应拒绝。恢复通信并续送 R1，实调前为 `{"L":5,"R":3}`，实调后为 `{"L":5,"R":5}`。原号重领不增加历史。复盘按序记录 L5、R1，最终试听混声为 `[10]`。
2. 在新场次分别发 G1 两格、G2 一格，等厅端答复 G1 后先扣住其回包，G2 须能先办理。台端此时至少可承诺 1 格。补齐两笔回证并重投，累计恰可承诺 3 格，第 4 格应拒绝。两笔远端原单可倒序送达，首执和复盘按实际顺序。可先把现场调到 4 格用完厅端余量，待现场降回 3 格后再发 1 格。原来超额的远端请求号可按最初参数重新申请这 1 格。同一已受理号改参仍冲突。
3. 分别在厅端兑现前扣住交件和在兑现后扣去回包。用原库重开，兑现前查单仍待办且听感不变，兑现后可查到同次首执。待办挡住收场，结清后扣去一次关闭交件或回包，并在关闭启动后交付迟到的发额回证。即使重开也不能凭该回证承诺新单，续办收场后可按号领到同一份复盘。

## 运行与核验

`margin_fixture.py` 提供可复用的 `routed_stack(directory)`。它返回台端端口、厅端直连端口和台厅代理。代理的 `offline.set()`、`offline.clear()` 控制整条台厅链路，直连厅端仍可操作。用 `arm(method, route, mode)` 对选定内部路由的下一次请求扣交件、扣回包或暂扣回包，模式分别为 `drop_before`、`drop_after`、`hold_after`。暂扣时 `entered` 在取得厅端响应后置位，通过 `release.set()` 放行。停栈后用同一目录重新开栈可重用两库。`python3 -B margin_fixture.py check` 用普通场次核验夹具。

`.pointwise-runtime.json` 已登记环回 API 的启动命令和就绪路径。保持 `version: 1`、`kind: api`、环回启动及就绪检查可用，`setup` 记录准备命令列表，`start`、`verify`、`demo` 各使用一组命令参数。运行核验须保留原回归并通过 HTTP 核对本题场景，断言失败须非零退出。运行演示须展示一次断链期间两边各自操作、重连兑现以及重开后凭报告号领取实调复盘的真实结果。

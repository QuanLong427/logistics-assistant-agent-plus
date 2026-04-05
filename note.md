# 用户从输入问题到输出答案的完整流程

本文说明这个项目中，用户输入一个问题后，系统如何一步步处理，直到生成最终答案。

---

## 1. 程序入口

主入口在 [main_pipeline.py](main_pipeline.py)。

批量运行时执行：

```bash
.venv\Scripts\python.exe main_pipeline.py --input data/test_input.json --output result/output.json
```

入口逻辑位于：
- [main_pipeline.py:201-212](main_pipeline.py#L201-L212)
- [main_pipeline.py:127-199](main_pipeline.py#L127-L199)

流程如下：
1. 创建 `MainPipeline()` 实例
2. 创建 `BatchProcessor(pipeline)`
3. 读取输入 JSON
4. 遍历每个用户、每轮对话
5. 对每个问题调用 `pipeline.process_user_input(user_id, question)`
6. 把结果写入 `output.json`

---

## 2. 启动时先检查向量数据库

在批处理开始时，会先检查向量数据库目录是否存在：
- [main_pipeline.py:132-137](main_pipeline.py#L132-L137)

逻辑：
- 如果 `settings.SAVE_EMBED_PATH` 不存在，或目录为空，就调用 `rag_retriever.build_embeddings()` 构建向量库
- 如果已存在，就直接加载

默认配置来自：
- [config/settings.py:12-35](config/settings.py#L12-L35)

关键配置：
- `ROOT_FOLDER`：知识库原始文档目录
- `SAVE_EMBED_PATH`：向量库保存目录
- `SAVE_OCR_REPORT`：图片识别报告路径
- `RAG_K`：RAG 返回文档数
- `TOP_K_PER_ROUTE` / `FINAL_TOP_K`：多路召回与重排序配置

---

## 3. 单轮请求主流程：`process_user_input`

核心逻辑在：
- [main_pipeline.py:16-118](main_pipeline.py#L16-L118)

这是系统处理一轮用户问题的总入口。

整体可以分为 5 层：

1. 读取历史记忆
2. 感知层：意图识别 + 问题重写
3. 信息抽取层：抽取结构化参数
4. 执行层：工具调用 + RAG 检索 + 回答生成
5. 风控层 + 历史写回

---

## 4. 第一步：加载历史对话与用户结构化信息

代码位置：
- [main_pipeline.py:18-31](main_pipeline.py#L18-L31)
- [utils/memory_manager.py:16-56](utils/memory_manager.py#L16-L56)
- [utils/data_loader.py:168-206](utils/data_loader.py#L168-L206)

系统先读取两类历史信息：

### 4.1 对话历史
来自：
- `data/chat_history/{user_id}.json`

读取逻辑：
- `memory_manager.load_history(user_id)`
- 底层调用 `data_loader.get_chat_history(user_id)`

作用：
- 给问题重写提供上下文
- 支持多轮对话

### 4.2 用户结构化信息
来自：
- `data/user_structured_info/{user_id}.json`

读取逻辑：
- `memory_manager.get_user_structured_info(user_id)`
- 底层调用 `data_loader.get_user_structured_info(user_id)`

作用：
- 记录用户上一轮提到的重要参数
- 比如订单号、城市、服务类型等
- 下一轮可以继续复用

---

## 5. 第二步：初始化流水线状态对象

代码位置：
- [main_pipeline.py:22-31](main_pipeline.py#L22-L31)
- [utils/pipeline_state.py:5-40](utils/pipeline_state.py#L5-L40)

系统会创建 `PipelineState`，保存本轮处理过程中的所有中间结果：

包含字段：
- `user_id`
- `original_query`
- `chat_history`
- `intent`
- `rewritten_query`
- `extracted_params`
- `tool_results`
- `rag_context`
- `final_answer`
- `risk_info`
- `is_success`
- `error_message`

可以把它理解成这一轮请求的“状态容器”。

---

## 6. 第三步：感知层并行执行

代码位置：
- [main_pipeline.py:34-45](main_pipeline.py#L34-L45)

系统会并行做两件事：

### 6.1 意图识别 `intent_recognizer.recognize_intent`
代码位置：
- [modules/perception/intent_recognizer.py](modules/perception/intent_recognizer.py)

处理方式：
1. 先做规则识别
2. 规则没命中，再调用 LLM

常见结果：
- `CHITCHAT`：闲聊
- `RESET`：重置会话
- `HUMAN_TRANSFER`：转人工
- `BUSINESS_QUERY`：业务查询

业务查询还会继续分子意图，例如：
- `TRACKING`：查订单状态
- `PRICE_QUERY`：查价格
- `DELIVERY_TIME`：查时效
- `ORDER_CREATE` / `SHIPMENT`：创建订单

### 6.2 问题重写 `query_rewriter.rewrite_query`
代码位置：
- [modules/perception/query_rewriter.py](modules/perception/query_rewriter.py)

处理方式：
1. 先把最近几轮历史对话格式化
2. 调用 LLM 把用户问题改写成更适合检索和抽取的表达

作用：
- 消解省略
- 利用上下文补全问题
- 提高信息抽取和 RAG 检索效果

并行完成后，把 `intent` 和 `rewritten_query` 写入 `PipelineState`。

---

## 7. 第四步：信息抽取层

代码位置：
- [main_pipeline.py:47-69](main_pipeline.py#L47-L69)
- [modules/extraction/information_extractor.py](modules/extraction/information_extractor.py)

只有当意图是 `BUSINESS_QUERY` 时，才会进入信息抽取。

### 7.1 抽取内容
系统会从重写后的问题里抽取结构化参数，例如：
- `origin_city`
- `dest_city`
- `weight`
- `service_type`
- `order_id`
- `tracking_number`
- `product_name`
- `quantity`
- `pickup_time`
- `contact_name`
- `contact_phone`

### 7.2 抽取方式
`information_extractor.extract_information(rewritten_query)` 会：
1. 把问题送给 LLM
2. 返回 JSON
3. 用 `json.loads` 解析成 Python 字典

### 7.3 与历史结构化信息合并
代码位置：
- [main_pipeline.py:53-65](main_pipeline.py#L53-L65)

如果系统之前已经记住过这个用户的结构化信息：
- 本轮抽出的非空字段会覆盖旧值
- 旧值中未被覆盖的字段会继续保留

这样用户就不需要每一轮都重复说订单号、城市等信息。

### 7.4 保存结构化信息
最终会保存回：
- `data/user_structured_info/{user_id}.json`

---

## 8. 第五步：执行层

代码位置：
- [main_pipeline.py:70-99](main_pipeline.py#L70-L99)

执行层分两种情况。

### 8.1 非业务查询
如果意图是：
- `CHITCHAT`
- `RESET`
- `HUMAN_TRANSFER`

那么：
- 不走工具调用
- 不走 RAG
- 直接生成回答

对应代码：
- [main_pipeline.py:71-79](main_pipeline.py#L71-L79)

### 8.2 业务查询
如果是 `BUSINESS_QUERY`，则依次做三件事：

1. 工具调用
2. RAG 检索
3. 生成回答

---

## 9. 第六步：工具调用

代码位置：
- [main_pipeline.py:82-83](main_pipeline.py#L82-L83)
- [modules/execution/tool_caller.py](modules/execution/tool_caller.py)

调用入口：
- `tool_caller.route_and_call(rewritten_query, state.extracted_params, intent, data_loader)`

### 9.1 工具路由规则
系统根据 `intent_type` 和 `sub_intent` 选择工具：

- `PRICE_QUERY` → `query_logistics_price`
- `TRACKING` → `track_order_status`
- `DELIVERY_TIME` → `calculate_delivery_time`
- `SHIPMENT` → `create_shipment`

### 9.2 参数检查
每个工具在调用前会检查参数是否齐全。

例如：
- 查订单状态必须有 `order_id`
- 查时效必须有 `origin_city` 和 `dest_city`
- 查价格必须有 `origin_city`、`dest_city`、`weight`

如果参数不足，不会真正调用工具，而是直接返回：
- `tool_name: null`
- `result: 缺少xxx参数`

### 9.3 业务数据来源
底层数据来自：
- [utils/data_loader.py](utils/data_loader.py)

会加载：
- `OMS.xlsx`：订单数据
- `TMS.xlsx`：运输数据
- `WMS.xlsx`：仓储数据

例如查询订单状态时：
1. 根据 `order_id` 从 OMS 中查订单
2. 拿到 `transport_id`
3. 再从 TMS 中查运输状态、当前位置、预计到达时间
4. 拼成字符串返回

---

## 10. 第七步：RAG 检索

代码位置：
- [main_pipeline.py:85-86](main_pipeline.py#L85-L86)
- [modules/execution/rag_retriever.py](modules/execution/rag_retriever.py)

调用入口：
- `rag_retriever.retrieve_documents(question, rewritten_query)`

### 10.1 RAG 的作用
当工具不能覆盖全部业务说明时，RAG 从知识库文档中检索补充材料。

知识来源主要是：
- `data/documents/` 下的文本
- 以及从图片中识别出来的表格内容

### 10.2 检索策略
这个项目用的是“多路召回 + 全局重排序”：
- 原始问题 + Dense 检索
- 原始问题 + Sparse(BM25) 检索
- 重写问题 + Dense 检索
- 重写问题 + Sparse(BM25) 检索

对应代码：
- [modules/execution/rag_retriever.py:101-143](modules/execution/rag_retriever.py#L101-L143)

### 10.3 融合与去重
四路结果会先合并、再根据 `point_id` 或文本内容去重。

对应代码：
- [modules/execution/rag_retriever.py:185-205](modules/execution/rag_retriever.py#L185-L205)

### 10.4 重排序
之后用重排序模型 `BAAI/bge-reranker-v2-m3` 对候选文档重新打分，挑出最相关的 Top-K。

对应代码：
- [modules/execution/rag_retriever.py:207-220](modules/execution/rag_retriever.py#L207-L220)

### 10.5 为什么会识别图片
在构建知识库时，项目不只处理文本，还会处理 `data/documents/*/图片/` 下的图片。

原因是：
- 很多业务规则、价格表、收费标准写在图片或表格截图里
- 如果不识别图片，这部分知识不会进入向量库
- 之后 RAG 检索就召回不到这些内容

因此，图片识别主要发生在**构建向量数据库阶段**，不是每次问答都重新扫描全部图片。

---

## 11. 第八步：回答生成

代码位置：
- [main_pipeline.py:91-98](main_pipeline.py#L91-L98)
- [modules/execution/answer_generator.py](modules/execution/answer_generator.py)

调用入口：
- `answer_generator.generate_answer(...)`

模型会综合以下输入生成最终回答：
- `intent`
- `rewritten_query`
- `extracted_params`
- `tool_results`
- `rag_context`

也就是说，最终回答不是只靠工具，也不是只靠 RAG，而是把两者一起喂给 LLM 组织成自然语言。

特殊意图会直接返回固定文案：
- 闲聊
- 重置
- 转人工

普通业务查询则由 LLM 生成完整回答。

---

## 12. 第九步：风控过滤

代码位置：
- [main_pipeline.py:100-102](main_pipeline.py#L100-L102)
- [modules/safety/risk_detector.py](modules/safety/risk_detector.py)

回答生成后，不会立刻返回，而是先经过风控。

### 12.1 风控方式
分两层：
1. 规则检测：看回答中是否包含敏感词
2. LLM 检测：再让模型判断是否有风险

### 12.2 风控结果
如果发现有风险：
- 直接替换成统一拒答文案

如果没风险：
- 保留原回答

最终结果写入：
- `safe_answer`
- `state.final_answer`

---

## 13. 第十步：写回对话历史

代码位置：
- [main_pipeline.py:104-109](main_pipeline.py#L104-L109)

系统会把本轮对话写回历史：
1. 追加用户消息
2. 追加助手回复
3. 保存到 `data/chat_history/{user_id}.json`

这样下一轮问答时，问题重写器就能看到最近几轮上下文。

---

## 14. 第十一步：返回并写入 output.json

单轮处理完成后：
- `state.to_dict()` 会把整个状态对象转成字典返回

批处理器会把结果整理成：
- `user_question`
- `system_response`
- `processing_details`

然后写入：
- `result/output.json`

对应代码：
- [main_pipeline.py:173-185](main_pipeline.py#L173-L185)
- [main_pipeline.py:189-199](main_pipeline.py#L189-L199)

---

## 15. 一张总流程图

```text
用户输入问题
    ↓
读取对话历史 + 用户结构化信息
    ↓
初始化 PipelineState
    ↓
并行执行：意图识别 + 问题重写
    ↓
如果是 BUSINESS_QUERY：抽取结构化参数
    ↓
合并历史结构化信息并保存
    ↓
业务查询分支：
    ├─ 工具调用（查订单/查价格/查时效/创建订单）
    ├─ RAG 检索（文本+图片知识库，多路召回+重排序）
    └─ 回答生成
    ↓
非业务分支：直接生成回答
    ↓
风险检测与过滤
    ↓
写回对话历史
    ↓
输出最终答案 + 中间过程到 output.json
```

---

## 16. 你在 output.json 里看到的字段是怎么来的

- `intent`：来自意图识别器
- `rewritten_query`：来自问题重写器
- `extracted_params`：来自信息抽取器 + 历史结构化信息合并
- `tool_results`：来自工具调用器
- `rag_context`：来自 RAG 检索器
- `risk_info`：理论上来自风控层，但当前主流程里没有显式写入详细风险对象，只写了过滤后的答案
- `system_response`：最终安全回答 `final_answer`

---

## 17. 这个项目当前流程的特点

### 优点
- 流程清晰，分层明确
- 支持多轮对话
- 支持结构化信息记忆
- 同时结合工具调用和 RAG
- RAG 用了多路召回和重排序，检索能力比单路强

### 当前需要注意的点
- 回答生成时，LLM 可能会把 RAG 内容当成当前订单事实来推断
- 工具结果和 RAG 结果冲突时，目前没有非常强的“工具事实优先”约束
- `risk_info` 在 `output.json` 中基本没有详细写回
- 向量库首次构建时会处理图片，因此第一次运行会较慢

---

## 18. 总结

这个项目从用户输入到最终回答的路径可以概括为：

**记忆读取 → 感知理解 → 参数抽取 → 工具执行 + 知识检索 → LLM生成 → 风控过滤 → 历史写回 → 输出结果**

其中：
- 工具负责查业务事实
- RAG 负责补充业务规则和说明
- LLM 负责把这些信息组织成自然语言回复

这就是整个项目的主处理链路。

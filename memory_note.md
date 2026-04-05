# 上下文历史处理逻辑笔记

本文专门说明这个项目里“上下文历史”是如何保存、读取、裁剪、格式化、参与推理，以及在多轮对话中如何影响回答生成的。

---

## 1. 历史对话是保存在内存里还是数据库里？

结论：

**不是只存在进程内存里，而是落盘保存在本地 JSON 文件中。**

具体位置：
- 对话历史：`data/chat_history/{user_id}.json`
- 用户结构化信息：`data/user_structured_info/{user_id}.json`

对应代码：
- [utils/data_loader.py:168-206](utils/data_loader.py#L168-L206)
- [utils/memory_manager.py:16-56](utils/memory_manager.py#L16-L56)

所以这个项目的“上下文记忆”本质上是：

1. **运行时读到 Python 变量里使用**
2. **处理结束后再写回本地文件**

它不是：
- 纯内存临时变量
- 也不是 MySQL / Redis 这类真正数据库

更准确说，它是**文件持久化的轻量记忆机制**。

---

## 2. 这个项目里“上下文历史”分成两类

这个项目不是只有一种历史，而是两套记忆同时存在。

### 2.1 对话历史 `chat_history`
作用：
- 保留用户和助手最近几轮说过的话
- 用于问题重写
- 用于多轮语义承接

数据结构示例：

```json
[
  {"role": "user", "content": "你好，我想查询订单状态"},
  {"role": "assistant", "content": "请提供订单号"},
  {"role": "user", "content": "订单号是JD202604040001"}
]
```

### 2.2 用户结构化信息 `user_structured_info`
作用：
- 保存从历史中抽取出来的关键信息
- 例如订单号、城市、重量、服务类型等
- 供下一轮工具调用直接复用

数据结构示例：

```json
{
  "order_id": "JD202604040001",
  "origin_city": "北京",
  "dest_city": "上海"
}
```

这两者的区别非常重要：

- `chat_history` 保存的是**原始自然语言上下文**
- `user_structured_info` 保存的是**从上下文沉淀出的结构化槽位信息**

---

## 3. 历史上下文是在哪里加载的

主入口在：
- [main_pipeline.py:18-20](main_pipeline.py#L18-L20)

代码逻辑：

```python
chat_history = memory_manager.load_history(user_id)
user_structured_info = memory_manager.get_user_structured_info(user_id)
```

也就是每次用户发来一个新问题，系统首先做的不是直接推理，而是：

1. 先读这个用户之前的对话历史
2. 再读这个用户之前沉淀的结构化信息

这一步决定了系统是不是“多轮对话系统”。

如果不做这一步，模型每轮都会把用户当成第一次来问问题。

---

## 4. `memory_manager.py` 在上下文逻辑中的作用

文件：
- [utils/memory_manager.py](utils/memory_manager.py)

它本身不负责复杂推理，而是一个**上下文历史管理器**，负责这几件事：

### 4.1 `load_history(user_id)`
- 读取该用户历史对话
- 底层调用 `data_loader.get_chat_history(user_id)`

### 4.2 `save_history(chat_history, user_id)`
- 把更新后的对话历史写回文件

### 4.3 `add_message(chat_history, role, content)`
- 给历史里追加一条消息
- 例如追加一条用户输入或助手回答

### 4.4 `get_recent_history(chat_history, max_length=None)`
- 取最近几条历史，而不是全量历史
- 默认长度来自 `settings.MAX_CHAT_HISTORY`

### 4.5 `format_history(chat_history)`
- 把最近几轮历史格式化成字符串
- 给问题重写器作为上下文输入

### 4.6 `get_user_structured_info(user_id)`
- 获取当前用户沉淀下来的结构化信息

### 4.7 `save_user_structured_info(user_id, structured_info)`
- 保存最新结构化信息

### 4.8 `update_user_structured_info(user_id, new_info)`
- 用新抽取的信息覆盖旧信息

---

## 5. 对话历史是怎么裁剪的

代码位置：
- [utils/memory_manager.py:10-14](utils/memory_manager.py#L10-L14)
- [config/settings.py:36-37](config/settings.py#L36-L37)

配置项：

```python
MAX_CHAT_HISTORY = 5
```

注意这里的逻辑是：

```python
return chat_history[-max_length:] if len(chat_history) > max_length else chat_history
```

这表示系统保留的是**最近 5 条消息**，不是最近 5 轮对话。

因为一轮对话通常有两条消息：
- user
- assistant

所以在当前实现下，`MAX_CHAT_HISTORY = 5` 大概只够覆盖：
- 2 轮完整对话 + 1 条新消息

这意味着：
- 上下文窗口其实偏短
- 如果对话长一点，比较早的信息会被截掉

---

## 6. 对话历史是怎么格式化给模型的

代码位置：
- [utils/memory_manager.py:33-36](utils/memory_manager.py#L33-L36)

逻辑：

```python
recent_history = MemoryManager.get_recent_history(chat_history)
return "\n".join([f"{msg['role']}：{msg['content']}" for msg in recent_history])
```

也就是说，模型看到的历史不是 JSON，而是这种文本：

```text
user：你好，我想查订单
assistant：请提供订单号
user：订单号是JD202604040001
assistant：正在为您查询
```

这个字符串会传给问题重写器。

---

## 7. 历史上下文是如何参与“问题重写”的

代码位置：
- [main_pipeline.py:35-42](main_pipeline.py#L35-L42)
- [modules/perception/query_rewriter.py:27-35](modules/perception/query_rewriter.py#L27-L35)

主流程里，问题重写和意图识别是并行的：

```python
intent_future = executor.submit(intent_recognizer.recognize_intent, question)
rewrite_future = executor.submit(query_rewriter.rewrite_query, question, chat_history)
```

而 `query_rewriter.rewrite_query()` 会：

1. 先把 `chat_history` 格式化
2. 再把 `question + formatted_history` 一起送给 LLM
3. 输出一个更完整、可检索的改写问题

这一步的核心目的，是让模型处理这种省略问法：

### 示例
上一轮：
- 用户：`我想查订单状态`
- 助手：`请提供订单号`

下一轮：
- 用户：`JD202604040001`

如果没有历史，上面这一句只是一个编号。
如果有历史，问题重写器可以把它改写成：

`请查询订单号为 JD202604040001 的订单状态。`

这就是上下文历史在多轮对话里最核心的价值。

---

## 8. 历史结构化信息是如何参与参数抽取的

代码位置：
- [main_pipeline.py:47-65](main_pipeline.py#L47-L65)

只有在 `BUSINESS_QUERY` 情况下，系统会抽取结构化参数：

```python
extracted_params = information_extractor.extract_information(rewritten_query)
```

然后会和历史结构化信息合并：

```python
if user_structured_info:
    for key, value in extracted_params.items():
        if value is not None:
            user_structured_info[key] = value
    extracted_params = user_structured_info
```

这个逻辑非常关键，意思是：

- 如果本轮抽到了新的非空值，就覆盖旧值
- 如果本轮没提到某个字段，就沿用历史值

### 示例
上一轮抽到：

```json
{
  "order_id": "JD202604040001"
}
```

下一轮用户说：

`那现在到哪了？`

本轮可能抽不到新的 `order_id`，但因为历史结构化信息里还保留着：

```json
{
  "order_id": "JD202604040001"
}
```

所以工具调用仍然可以继续查这个订单。

这说明：

> 对话历史主要帮助模型“理解问题”
> 结构化历史主要帮助工具“拿到参数”

---

## 9. 历史结构化信息为什么重要

因为工具调用是强依赖参数的。

例如：
- 查订单状态必须要 `order_id`
- 查时效必须要 `origin_city` 和 `dest_city`
- 查价格还要 `weight`

如果没有结构化记忆，那么用户每轮都要重新把这些参数说一遍。

有了结构化历史之后，系统可以支持这种自然多轮：

### 示例 1：查单
- 第1轮：`我想查订单状态`
- 第2轮：`订单号是JD202604040001`
- 第3轮：`那现在到哪了？`

第3轮虽然没说订单号，但系统仍然可以用上一轮保存的 `order_id` 去查。

### 示例 2：查时效
- 第1轮：`从北京发上海多少钱`
- 第2轮：`3公斤`
- 第3轮：`那多久能到？`

如果历史结构化信息里已保存：
- `origin_city=北京`
- `dest_city=上海`
- `weight=3公斤`

那么系统下一轮就能承接继续算时效或价格。

---

## 10. 历史是如何影响工具调用的

代码位置：
- [main_pipeline.py:82-83](main_pipeline.py#L82-L83)
- [modules/execution/tool_caller.py:48-168](modules/execution/tool_caller.py#L48-L168)

工具调用使用的是：

```python
tool_caller.route_and_call(rewritten_query, state.extracted_params, intent, data_loader)
```

注意第二个参数是：
- `state.extracted_params`

而 `state.extracted_params` 很多时候并不是“仅本轮抽取结果”，而是：

**本轮抽取结果 + 历史结构化信息合并后的结果**

所以历史信息会直接影响：
- 选哪个工具
- 工具能不能调用
- 调工具时带什么参数

---

## 11. 历史是如何写回的

代码位置：
- [main_pipeline.py:104-109](main_pipeline.py#L104-L109)

本轮处理完成后：

```python
updated_history = memory_manager.add_message(chat_history, "user", question)
updated_history = memory_manager.add_message(updated_history, "assistant", safe_answer)
memory_manager.save_history(updated_history, user_id)
```

也就是：

1. 把当前用户提问追加到历史里
2. 把当前系统回答追加到历史里
3. 把完整历史保存回 `data/chat_history/{user_id}.json`

所以历史是**逐轮累积**的，不是每次运行都只放在内存里。

---

## 12. 当前上下文历史逻辑的整体链路

可以概括成下面这条线：

```text
收到新问题
  ↓
根据 user_id 读取历史对话 chat_history
  ↓
根据 user_id 读取历史结构化信息 user_structured_info
  ↓
把 chat_history 传给 query_rewriter 做问题重写
  ↓
把 rewritten_query 送给 information_extractor 抽结构化参数
  ↓
把新参数与 user_structured_info 合并
  ↓
合并后的参数进入 tool_caller
  ↓
最终生成回答
  ↓
把本轮 user / assistant 消息写回 chat_history 文件
  ↓
把更新后的结构化参数写回 user_structured_info 文件
```

---

## 13. 这个项目的上下文历史处理优点

### 优点 1：实现简单
只依赖 JSON 文件，不需要搭数据库。

### 优点 2：支持真正的多轮对话
用户下一轮可以省略前文信息。

### 优点 3：把“自然语言历史”和“结构化记忆”分开
这是合理设计：
- 一个给 LLM 理解语义
- 一个给工具拿参数

### 优点 4：有滑动窗口
不会把所有历史无限喂给模型，能控制上下文长度。

---

## 14. 当前实现需要注意的问题

### 问题 1：`MAX_CHAT_HISTORY=5` 实际偏短
因为它按“消息条数”裁剪，而不是按“轮次”裁剪。

### 问题 2：结构化信息会跨轮持续保留
这在多数场景是好事，但如果用户切换话题，旧参数可能污染新问题。

### 问题 3：问题重写器可能“改写过度”
历史越多，LLM 越容易把推断写进改写结果里，导致后续抽取和 RAG 方向偏掉。

### 问题 4：没有显式的话题切换清理机制
除非用户触发 `RESET`，否则旧结构化信息会一直保留。

---

## 15. 你可以如何理解这个项目的“上下文管理”

如果一句话总结：

> 这个项目的上下文管理，不是把所有历史都直接喂给最终回答模型，而是把历史拆成“对话文本上下文”和“结构化槽位记忆”两条线分别使用。

更具体地说：

- `chat_history` → 主要服务于问题重写
- `user_structured_info` → 主要服务于参数承接与工具调用
- 最终回答阶段更多依赖的是：
  - 当前轮的意图
  - 当前轮/历史合并后的参数
  - 工具结果
  - RAG 检索结果

---

## 16. 最后总结

这个项目的上下文历史处理逻辑，本质是一个“文件持久化 + 滑动窗口 + 结构化槽位继承”的多轮对话方案。

它的核心思想是：

1. **历史对话保存在本地 JSON 文件中**，不是纯内存
2. **每次新请求都会读取历史**
3. **最近历史用于问题重写**
4. **历史结构化信息用于参数承接**
5. **回答结束后再把新历史写回文件**

所以它已经具备了基本的上下文管理能力，只是当前实现还比较轻量，离更稳健的“上下文优化”还有继续完善空间。

# 项目运行指南

## 环境要求

- Python 3.8+
- uv (已安装)
- 通义千问 API Key

## 快速开始

### 1. 安装依赖

使用 uv 安装项目依赖：

```bash
# 创建虚拟环境（推荐）
uv venv

# 在虚拟环境中安装依赖
uv pip install -r requirements.txt --python .venv/Scripts/python.exe
```

**注意**：项目已修复 LangChain 1.2+ 版本的兼容性问题：
- 将 `from langchain.prompts import PromptTemplate` 改为 `from langchain_core.prompts import PromptTemplate`
- 将 `LLMChain` 替换为 LCEL 语法 `prompt | llm`
- 将 `from langchain.text_splitter` 改为 `from langchain_text_splitters`

### 2. 配置环境变量

编辑 `.env` 文件，设置你的通义千问 API Key：

```bash
DASHSCOPE_API_KEY=你的实际API密钥
```

**重要提示**：
- 必须配置有效的 API Key，否则无法调用大模型服务
- 这个 API Key 用于所有模型调用（Embedding、LLM、Vision）
- 可在[阿里云 DashScope 控制台](https://dashscope.console.aliyun.com/)获取

**已修复的配置问题**：
- 重排序模型配置已从中文占位符改为 `BAAI/bge-reranker-v2-m3`

### 3. 数据准备

项目已包含以下数据：
- `data/database/` - 业务数据库（OMS.xlsx, TMS.xlsx, WMS.xlsx）
- `data/documents/` - 知识库文档

### 4. 运行项目

#### 方式A：使用虚拟环境运行（推荐）

```bash
# Windows
.venv\Scripts\python.exe main_pipeline.py --input data/test_input.json --output result/output.json

# Linux/Mac
.venv/bin/python main_pipeline.py --input data/test_input.json --output result/output.json
```

#### 方式B：生成测试数据并运行完整流程

```bash
# 步骤1：生成黄金测试集
.venv\Scripts\python.exe generate_data.py --output data/golden_test_set.jsonl --sample-size 100

# 步骤2：转换为系统输入格式
.venv\Scripts\python.exe data/convert_test_set_to_input.py \
  --golden-file data/golden_test_set.jsonl \
  --output-file data/test_input.json \
  --users-count 5

# 步骤3：运行主流水线
.venv\Scripts\python.exe main_pipeline.py --input data/test_input.json --output result/output.json
```

**首次运行注意事项**：
- 系统会自动构建向量数据库（需要时间）
- 会自动下载重排序模型 BAAI/bge-reranker-v2-m3（约 600MB）
- 建议首次运行时耐心等待模型下载完成

### 5. 评估结果

```bash
python evaluate.py \
  --input-file data/test_input.json \
  --result-file result/output.json
```

## 项目架构

```
感知层 -> 信息抽取层 -> 执行层 -> 风控层
```

1. **感知层**：意图识别 + 问题重写（并行执行）
2. **信息抽取层**：提取结构化参数，合并历史信息
3. **执行层**：工具调用 + RAG检索（混合检索 + 重排序）
4. **风控层**：风险检测

## 核心特性

- ✅ 多轮对话支持
- ✅ 用户结构化信息记忆
- ✅ 混合检索（Dense + Sparse）
- ✅ 多路召回 + BGE-M3 重排序
- ✅ 对话历史长度管理

## 常见问题

### Q1: 首次运行很慢？
A: 首次运行会：
- 构建向量数据库（需要时间）
- 下载重排序模型 BAAI/bge-reranker-v2-m3（约 600MB）
- 后续运行会直接加载已构建的向量库和缓存的模型

### Q2: API 调用失败？
A: 检查 `.env` 文件中的 `DASHSCOPE_API_KEY` 是否配置正确。

### Q3: 如何修改模型配置？
A: 编辑 `config/settings.py` 文件，修改模型名称、检索参数等配置。

### Q4: ModuleNotFoundError 错误？
A: 确保使用虚拟环境中的 Python：
```bash
# Windows
.venv\Scripts\python.exe main_pipeline.py ...

# Linux/Mac
.venv/bin/python main_pipeline.py ...
```

### Q5: LangChain 导入错误？
A: 项目已修复 LangChain 1.2+ 版本兼容性问题。如果仍有问题，请重新安装依赖：
```bash
uv pip install -r requirements.txt --python .venv/Scripts/python.exe
```

### Q6: Windows 控制台乱码 / 程序中断？
A: 如果在 Windows 下运行时出现 `UnicodeEncodeError: 'gbk' codec can't encode character`，说明代码里的 emoji 输出与 Windows 默认 GBK 编码冲突。

**现象**：
- 程序在启动或打印进度时中断
- 典型报错位置在 [main_pipeline.py](main_pipeline.py)

**解决方法**：
1. 移除 `print()` 中的 emoji 字符，如 `🔔`、`📥`、`🏗️`、`📚`、`👤`、`💬`、`✅`、`📤`
2. 改成纯文本输出
3. 重新运行：
```bash
.venv\Scripts\python.exe main_pipeline.py --input data/test_input.json --output result/output.json
```

### Q7: 向量数据库是否构建成功？
A: 判断方式：

1. 检查目录 [data/rag_knowledge_base/](data/rag_knowledge_base/)
2. 若存在 `index.faiss` 和 `index.pkl`，说明向量数据库已构建成功
3. 检查 [image_ocr_report.txt](image_ocr_report.txt) 是否仍有 `❌ 模型调用失败`

当前项目重新构建后的结果：
- `data/rag_knowledge_base/index.faiss` 已生成
- `data/rag_knowledge_base/index.pkl` 已生成
- `image_ocr_report.txt` 中图片 OCR 失败数为 0

说明：**向量数据库已经构建成功，且图片 OCR 已成功写入知识库。**

## 开发建议

### 使用 uv 的优势

- 更快的依赖安装速度
- 更好的依赖解析
- 内置虚拟环境管理

### 推荐工作流

```bash
# 1. 激活虚拟环境
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# 2. 开发调试
python main_pipeline.py --input your_input.json --output your_output.json

# 3. 评估性能
python evaluate.py --input-file your_input.json --result-file your_output.json
```

## 已完成的修复

- ✅ 修复 LangChain 1.2+ 版本兼容性问题
  - 更新 `PromptTemplate` 导入路径
  - 将 `LLMChain` 替换为 LCEL 语法
  - 更新 `RecursiveCharacterTextSplitter` 和 `Document` 导入
- ✅ 修复 Windows 控制台编码问题（移除 emoji）
- ✅ 修复 .env 配置文件中的中文占位符
- ✅ 配置正确的重排序模型路径

## 下一步优化方向

- [ ] 改进数据生成方式
- [ ] 使用大模型进行真值打标
- [ ] 实现父子检索方式
- [ ] 探索更强的重排序模型（Qwen-Reranker）
- [ ] 优化上下文压缩策略
- [ ] 添加更多业务工具
- [ ] 优化首次运行体验（预下载模型）
- [ ] 添加进度条显示

## 技术栈

- LangChain - Agent 框架
- FAISS - 向量数据库
- Qwen-Embedding - 嵌入模型
- BGE-M3 - 重排序模型
- BM25 - 稀疏检索
- Pydantic - 数据验证

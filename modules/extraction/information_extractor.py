from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
import json
from config import settings
from config import prompts
import logging

class InformationExtractor:
    """信息抽取器"""

    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=settings.DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name=settings.QA_MODEL_NAME,
            temperature=0.1
        )
        self.prompt = PromptTemplate(
            input_variables=["question"],
            template=prompts.INFORMATION_EXTRACTION["dynamic"]
        )
        # 系统提示词
        self.system_prompt = prompts.INFORMATION_EXTRACTION["system"]
        # 使用 LCEL 语法替代 LLMChain
        self.chain = self.prompt | self.llm

    def extract_information(self, question: str) -> Dict[str, Any]:
        """抽取结构化信息"""
        logging.info(f"开始抽取信息：{question}")
        result = self.chain.invoke({"question": question}).content
        logging.info(f"抽取到的信息原始结果：{result}")
        extracted_info = json.loads(result)
        return extracted_info


# 创建全局信息抽取器实例
information_extractor = InformationExtractor()
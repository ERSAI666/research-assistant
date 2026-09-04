from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError
import logging
import requests
import time
import os

load_dotenv()

logger = logging.getLogger(__name__)
api_key = os.getenv("TAVILY_API_KEY")
endpoint = os.getenv("TAVILY_BASE_URL")
CONTENT_MAX_LEN = 500
MAX_RETRIES = 3
search_cache = {}


class TavilySingleResult(BaseModel):
    title: str = Field(description="网页标题")
    content: str = Field(description="网页摘要内容")
    url: str = Field(description="网页链接")


def retry_wait(attempt: int, max_retries: int, resp=None) -> int | None:
    """返回重试需要等待的秒数，若无需重试则返回 None"""
    if attempt == max_retries:
        return None
    wait = 2**attempt
    if resp is not None and resp.status_code == 429:
        retry_after = resp.headers.get('Retry-After')
        wait = int(retry_after) if retry_after else 2**attempt
    return wait


def web_search(query: str) -> str:
    """
    联网搜索工具，用于获取互联网公开信息、行业数据、新闻、政策。
    参数:
        query: 清晰准确的搜索关键词
    """
    if query in search_cache:
        return f"【缓存结果】\n{search_cache[query]}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "query": query,
        "max_results": 3,
        "search_depth": "basic",
        "include_answer": False
    }

    for attempt in range(1, MAX_RETRIES+1):
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=10)

            if resp.status_code == 429 or resp.status_code >= 500:
                wait = retry_wait(attempt, MAX_RETRIES, resp=resp)
                if wait is None:
                    resp.raise_for_status()
                logger.debug(f"状态码{resp.status_code}，等待{wait}秒后重试（第{attempt}次）")
                time.sleep(wait)
                continue

            resp.raise_for_status()

            data = resp.json()
            raw_items = data.get("results", [])
            data_list = []
            for item in raw_items:
                try:
                    valid_item = TavilySingleResult(**item)
                    if len(valid_item.content) > CONTENT_MAX_LEN:
                        valid_item.content = valid_item.content[:CONTENT_MAX_LEN]
                    data_list.append(valid_item)
                except ValidationError as e:
                    logger.warning(f"跳过无效的搜索结果{e}")
                    continue

            if not data_list:
                result_str = f"搜索「{query}」未找到相关公开结果。"
                search_cache[query] = result_str
                return result_str

            output = ""
            for idx, obj in enumerate(data_list):
                output += f"{idx + 1}.标题：{obj.title}\n摘要：{obj.content}\n链接：{obj.url}\n\n"
            output = output.strip()
            search_cache[query] = output
            logger.debug(f"搜索完成，原始结果：\n{output}")
            return output

        except requests.exceptions.Timeout:
            wait = retry_wait(attempt, MAX_RETRIES)
            if wait is None:
                return f"搜索「{query}」超时，请稍后重试。"
            logger.debug(f"请求超时，等待{wait}秒后重试（第{attempt}次）")
            time.sleep(wait)
            continue

        except requests.exceptions.HTTPError as s:
            return f"搜索「{query}」接口返回错误状态码：{s.response.status_code}"

        except Exception as e:
            return f"搜索「{query}」失败，错误信息：{str(e)}"

    return f"搜索「{query}」多次失败"

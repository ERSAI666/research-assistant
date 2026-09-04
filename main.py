from schemas import SubQuestionList, ResearchNote, ResearchReport
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from tools import web_search
import asyncio
import logging
import os


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()


def init_llm():
    llm = ChatOpenAI(
        model="qwen3.7-flash",
        api_key=os.getenv("QWEN_API_KEY"),
        base_url=os.getenv("QWEN_BASE_URL"),
        temperature=0.1
    )
    return llm


async def topic_split(model: ChatOpenAI, topic: str) -> list[str]:
    logger.info("正在拆解研究模型...")
    structured_model = model.with_structured_output(SubQuestionList, method="function_calling")
    prompt_split = f"""
        请将研究主题「{topic}」拆解为3个需要检索的子问题，覆盖市场、政策、趋势等核心维度。
        严格按照以下JSON格式输出，不要多余解释文字：
        {{
            "sub_questions": [
                {{"question": "子问题1"}},
                {{"question": "子问题2"}},
                {{"question": "子问题3"}}
            ]
        }}
        """
    try:
        result = await structured_model.ainvoke(prompt_split)
        questions = [item.question for item in result.sub_questions]
    except Exception as e:
        logger.warning(f"主题拆解失败，将使用默认维度，错误信息：\n{e}")
        default_dims = ["市场现状", "发展趋势", "政策环境"]
        questions = [f"{topic}{dim}" for dim in default_dims]
    for i, q in enumerate(questions):
        logger.info(f"{i + 1}.{q}")
    return questions


async def search_question(model: ChatOpenAI, question: str) -> ResearchNote:
    search_result = await asyncio.to_thread(web_search, question)
    logger.debug(f"问题[{question}]原始搜索结果：\n{search_result}")
    structured_model = model.with_structured_output(ResearchNote, method="function_calling")
    prompt_search = f"""
        基于以下搜索结果，提取核心信息，生成结构化研究笔记。
        搜索问题：{question}
        搜索结果：
        {search_result}
        要求：
        1. key_points 提取4-5条关键信息，包括事实、数据、观点
        2. 有多少提取多少，禁止编造信息凑数
        3. 若包含具体数字、日期、定量结论，务必完整提取
        4. source_title 和 source_url 取第一条最相关的来源
        5. 严格基于搜索结果，禁止编造内容
        """
    try:
        note = await structured_model.ainvoke(prompt_search)
        return note
    except Exception as e:
        logger.warning(f"笔记提取失败，将降级为原始内容，错误信息：{e}")
        if len(search_result.strip()) > 500:
            clean_content = search_result.strip()[:500]+"\n···【原文过长，此处内容截断】···"
        else:
            clean_content = search_result.strip()
        return ResearchNote(
            key_points=[clean_content] if clean_content else ["无有效信息"],
            source_title=f"原始搜索问题：{question}",
            source_url=""
        )


async def collect_notes(model: ChatOpenAI, questions: list[str]) -> list[ResearchNote]:
    logger.info("正在并发检索信息...")
    tasks = [search_question(model, q) for q in questions]
    notes = await asyncio.gather(*tasks)
    logger.info(f"完成 {len(notes)} 个子问题检索")
    return list(notes)


def format_report(topic: str, report: ResearchReport, url_title_map: dict[str, str]) -> str:
    md = []
    md.append(f"# {topic} 研究报告")
    md.append("")
    md.append("## 一、核心结论")
    md.append("")
    md.append(report.core_conclusion.strip().replace("\\n", "\n"))
    md.append("")
    md.append("## 二、详细分析")
    md.append("")
    for idx, point in enumerate(report.detailed_analysis, 1):
        md.append(f"{point.strip().replace('\\n', '\n')}")
        md.append("")
    md.append("## 三、参考来源")
    md.append("")
    if url_title_map:
        for num, (url, title) in enumerate(url_title_map.items(), 1):
            md.append(f"[{num}][{title}]({url})  ")
    else:
        md.append("无明确来源记录")
    return "\n".join(md)


def format_fallback_report(topic: str, notes: list[ResearchNote]) -> str:
    md = []
    md.append(f"# {topic} 研究报告（降级版本）")
    md.append("")
    md.append("因生成异常，以下为原始笔记汇总。")
    md.append("")
    for i, note in enumerate(notes, 1):
        md.append(f"## 笔记 {i}")
        if note.key_points:
            for point in note.key_points:
                md.append(f"-{point.strip()}")
        else:
            md.append("- 无有效信息")
        title = note.source_title.strip() if note.source_title else "未记录标题"
        line = f"来源：{title}"
        if note.source_url:
            line += f" ({note.source_url})"
        md.append(line)
        md.append("")
        md.append("---")
        md.append("")
    return "\n".join(md)


async def generate_report(model: ChatOpenAI, topic: str, notes: list[ResearchNote]) -> tuple[str, str]:
    logger.info("正在生成研究报告...")
    context = ""
    for i, note in enumerate(notes, 1):
        context += f"### 笔记{i}\n"
        context += "核心观点：\n"
        if note.key_points:
            for p in note.key_points:
                context += f"- {p}\n"
        else:
            context += "- 无有效信息\n"
        context += f"来源：{note.source_title}\n链接：{note.source_url}\n\n"

    structured_llm = model.with_structured_output(ResearchReport, method="function_calling")
    prompt_generate = f"""
        研究主题：{topic}
        以下是全部研究笔记：
        {context}
        
        请基于以上笔记生成正式研究报告。
        要求：
        1. 核心结论控制在800字以内，高度概括核心发现
        2. 详细分析分点阐述，对应子问题维度
        3. 严格基于笔记内容，禁止编造笔记中没有的信息
        """
    try:
        report = await structured_llm.ainvoke(prompt_generate)
        url_title_map = {}
        for item in notes:
            if item.source_url and item.source_url.strip():
                url = item.source_url.strip()
                if url not in url_title_map:
                    title = item.source_title.strip() if item.source_title and item.source_title.strip() else "网页链接"
                    url_title_map[url] = title
        md = format_report(topic, report, url_title_map)
    except Exception as e:
        logger.error(f"结构化生成失败，将降级输出汇总版，错误信息：{e}")
        md = format_fallback_report(topic, notes)

    safe_name = topic.replace("/", "_").replace(" ", "")[:30]
    file_path = f"{safe_name}_研究报告.md"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md)

    return md, file_path


async def main():
    try:
        model = init_llm()

        topic = input("请输入研究主题：")
        logger.info(f"=== 研究任务启动：{topic} ===")

        sub_questions = await topic_split(model, topic)
        notes = await collect_notes(model, sub_questions)
        report, file_path = await generate_report(model, topic, notes)

        logger.info("=== 研究完成 ===")
        logger.info(f"报告已保存至：{file_path}")

    except Exception as e:
        logger.error(f"任务执行异常：{e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())

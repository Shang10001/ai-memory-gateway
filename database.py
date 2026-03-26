"""
数据库模块 —— 负责所有跟 PostgreSQL 打交道的事情
==============================================
包括：
- 创建表结构
- 存储对话记录
- 存储/检索记忆（带中文分词和加权排序）
"""

import os
import re
from typing import Optional, List

import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "")

# 搜索权重（向量搜索加入后可重新分配）
WEIGHT_KEYWORD = float(os.getenv("WEIGHT_KEYWORD", "0.5"))
WEIGHT_IMPORTANCE = float(os.getenv("WEIGHT_IMPORTANCE", "0.3"))
WEIGHT_RECENCY = float(os.getenv("WEIGHT_RECENCY", "0.2"))
MIN_SCORE_THRESHOLD = float(os.getenv("MIN_SCORE_THRESHOLD", "0.15"))


# ============================================================
# 连接池管理
# ============================================================

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL 未设置！")
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        print("✅ 数据库连接池已创建")
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        print("✅ 数据库连接池已关闭")


# ============================================================
# 表结构初始化
# ============================================================

async def init_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id              SERIAL PRIMARY KEY,
                session_id      TEXT NOT NULL,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL,
                model           TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id              SERIAL PRIMARY KEY,
                content         TEXT NOT NULL,
                importance      INTEGER DEFAULT 5,
                source_session  TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                last_accessed   TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                id              SERIAL PRIMARY KEY,
                category        TEXT UNIQUE NOT NULL,
                profile_data    JSONB NOT NULL,
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_fts 
            ON memories 
            USING gin(to_tsvector('simple', content));
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_session 
            ON conversations (session_id, created_at);
        """)
    
    print("✅ 数据库表结构已就绪")


# ============================================================
# 中文分词工具（基于 jieba）
# ============================================================

import jieba
import jieba.analyse

# 静默加载词典
jieba.setLogLevel(jieba.logging.INFO)

EN_WORD_PATTERN = re.compile(r'[a-zA-Z][a-zA-Z0-9]*')
NUM_PATTERN = re.compile(r'\d{2,}')

# 中文停用词（高频但无搜索价值的词，增加更多日常废话）
_STOP_WORDS = frozenset({
    "的", "了", "在", "是", "我", "你", "他", "她", "它", "们",
    "这", "那", "有", "和", "与", "也", "都", "又", "就", "但",
    "而", "或", "到", "被", "把", "让", "从", "对", "为", "以",
    "及", "等", "个", "不", "没", "很", "太", "吗", "呢", "吧",
    "啊", "嗯", "哦", "哈", "呀", "嘛", "么", "啦", "哇", "喔",
    "会", "能", "要", "想", "去", "来", "说", "做", "看", "给",
    "上", "下", "里", "中", "大", "小", "多", "少", "好", "可以",
    "什么", "怎么", "如何", "哪里", "哪个", "为啥", "为什么", "还是",
    "然后", "因为", "所以", "虽然", "但是", "已经", "一个", 
    "一些", "一下", "一点", "一起", "一样", "比较", "应该", 
    "可能", "如果", "这个", "那个", "自己", "知道", "觉得", 
    "感觉", "时候", "现在",
    # --- 新增的日常废话 ---
    "好", "好的", "好吧", "是的", "对", "对的", "行吧", "行", "嗯嗯", 
    "哈哈", "嘿嘿", "呜呜", "嘤嘤", "原来", "这样", "那样"
})


def extract_search_keywords(query: str) -> List[str]:
    """
    从查询中提取搜索关键词：
    1. 自动剔除 Emoji、颜文字及各种特殊符号
    2. 过滤停用词和单字
    """
    # 【核心改动】用正则洗掉所有非汉字、非字母、非数字的内容
    # 这步会直接把 🌀👃🌀、(✿ᴗ͈ˬᴗ͈)、🍎 等通通变成空格
    clean_query = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', ' ', query)
    
    keywords = set()

    # 英文单词（2字符以上）
    for match in EN_WORD_PATTERN.finditer(clean_query):
        word = match.group()
        if len(word) >= 2:
            keywords.add(word)

    # 数字串（2位以上）
    for match in NUM_PATTERN.finditer(clean_query):
        keywords.add(match.group())

    # 中文分词（使用清洗后的文本）
    words = jieba.cut(clean_query, cut_all=False)
    for word in words:
        word = word.strip()
        if not word:
            continue
        if EN_WORD_PATTERN.fullmatch(word) or NUM_PATTERN.fullmatch(word):
            continue
        # 跳过单字和停用词
        if len(word) < 2 or word in _STOP_WORDS:
            continue
        keywords.add(word)

    return list(keywords)


# ============================================================
# 对话记录操作
# ============================================================

async def save_message(session_id: str, role: str, content: str, model: str = ""):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (session_id, role, content, model) VALUES ($1, $2, $3, $4)",
            session_id, role, content, model,
        )


async def get_recent_messages(session_id: str, limit: int = 20):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content, created_at FROM conversations WHERE session_id = $1 ORDER BY created_at DESC LIMIT $2",
            session_id, limit,
        )
        return list(reversed(rows))


# ============================================================
# 记忆操作
# ============================================================

async def save_memory(content: str, importance: int = 5, source_session: str = ""):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO memories (content, importance, source_session) VALUES ($1, $2, $3)",
            content, importance, source_session,
        )


async def search_memories(query: str, limit: int = 10):
    """
    搜索相关记忆 —— 中文友好的加权搜索
    
    流程：
    1. 从查询中提取关键词（中文bigram/trigram + 英文单词 + 数字）
    2. 用 ILIKE 逐关键词匹配，统计命中数
    3. 加权排序：
       - 关键词命中率 * 0.5（命中越多越相关）
       - 重要程度    * 0.3（importance 1-10 归一化）
       - 崭新度      * 0.2（越新分越高，按天衰减）
    """
    keywords = extract_search_keywords(query)
    
    if not keywords:
        return []
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 每个关键词命中得1分
        case_parts = []
        params = []
        for i, kw in enumerate(keywords):
            case_parts.append(f"CASE WHEN content ILIKE '%' || ${i+1} || '%' THEN 1 ELSE 0 END")
            params.append(kw)
        
        hit_count_expr = " + ".join(case_parts)
        max_hits = len(keywords)
        
        # 至少命中一个关键词
        where_parts = [f"content ILIKE '%' || ${i+1} || '%'" for i in range(len(keywords))]
        where_clause = " OR ".join(where_parts)
        
        limit_idx = len(keywords) + 1
        params.append(limit)
        
        # 综合评分公式
        # recency: 今天≈1.0, 1天前≈0.5, 7天前≈0.125
        sql = f"""
            SELECT 
                id, content, importance, created_at,
                ({hit_count_expr}) AS hit_count,
                (
                    {WEIGHT_KEYWORD} * ({hit_count_expr})::float / {max_hits}.0 +
                    {WEIGHT_IMPORTANCE} * importance::float / 10.0 +
                    {WEIGHT_RECENCY} * (1.0 / (1.0 + EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400.0))
                ) AS score
            FROM memories
            WHERE {where_clause}
            ORDER BY score DESC, importance DESC, created_at DESC
            LIMIT ${limit_idx}
        """
        
        results = await conn.fetch(sql, *params)
        
        # 过滤低分记忆
        if MIN_SCORE_THRESHOLD > 0:
            before_count = len(results)
            results = [r for r in results if r['score'] >= MIN_SCORE_THRESHOLD]
            filtered = before_count - len(results)
        else:
            filtered = 0
        
        if results:
            print(f"🔍 搜索 '{query}' → 关键词 {keywords[:8]}{'...' if len(keywords)>8 else ''} → 命中 {len(results)} 条" + (f"（过滤 {filtered} 条低分）" if filtered else ""))
            for r in results[:3]:
                print(f"   📌 [score={r['score']:.3f}] (hits={r['hit_count']}, imp={r['importance']}) {r['content'][:60]}...")
            
            ids = [r["id"] for r in results]
            await conn.execute(
                "UPDATE memories SET last_accessed = NOW() WHERE id = ANY($1::int[])",
                ids,
            )
        else:
            print(f"🔍 搜索 '{query}' → 关键词 {keywords[:8]} → 无结果" + (f"（{filtered} 条被分数阈值过滤）" if filtered else ""))
        
        return results


async def get_recent_memories(limit: int = 20):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, content, importance, created_at FROM memories ORDER BY created_at DESC LIMIT $1",
            limit,
        )


async def get_all_memories_count():
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM memories")
        return row["cnt"]


async def get_all_memories():
    """导出所有记忆（用于备份）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT content, importance, source_session, created_at FROM memories ORDER BY id"
        )
        return [dict(r) for r in rows]


async def get_all_memories_detail():
    """获取所有记忆（含 id，用于管理页面）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, content, importance, source_session, created_at FROM memories ORDER BY id"
        )
        return [dict(r) for r in rows]


async def update_memory(memory_id: int, content: str = None, importance: int = None):
    """更新单条记忆"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if content is not None and importance is not None:
            await conn.execute(
                "UPDATE memories SET content = $1, importance = $2 WHERE id = $3",
                content, importance, memory_id
            )
        elif content is not None:
            await conn.execute(
                "UPDATE memories SET content = $1 WHERE id = $2",
                content, memory_id
            )
        elif importance is not None:
            await conn.execute(
                "UPDATE memories SET importance = $1 WHERE id = $2",
                importance, memory_id
            )


async def delete_memory(memory_id: int):
    """删除单条记忆"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM memories WHERE id = $1", memory_id)


async def delete_memories_batch(memory_ids: list):
    """批量删除记忆"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM memories WHERE id = ANY($1::int[])", memory_ids
        )


# ============================================================
# 遗忘机制（清理长期未访问且情绪低落的小事）
# ============================================================
import random

async def forget_old_memories(days_threshold: int = 180, min_importance: int = 7) -> int:
    """
    淘汰机制：模拟大脑清理无用记忆
    - 超过 days_threshold（默认180天）未访问的记忆进入海选
    - importance（重要性/情感权重）达到 min_importance（默认7分）的记忆，拥有免死金牌，绝对不忘
    - 其他记忆根据权重计算遗忘概率：分数越低，越容易被遗忘
    返回：成功清理的记忆数量
    """
    pool = await get_pool()
    forgotten_count = 0
    
    async with pool.acquire() as conn:
        # 1. 海选：找出所有超过指定天数没被访问过，且重要程度低于免死金牌的记忆
        sql_select = f"""
            SELECT id, content, importance 
            FROM memories 
            WHERE last_accessed < NOW() - INTERVAL '{days_threshold} days'
            AND importance < $1
        """
        candidates = await conn.fetch(sql_select, min_importance)
        
        ids_to_delete = []
        for mem_id, content, importance in candidates:
            # 2. 算命：把 importance (1-10分) 转换成一个 0.1 到 1.0 之间的情感权重
            emo_weight = importance / 10.0
            
            # 3. 行刑概率：权重越低，忘得越快。
            # 比如 5分的日常，被忘概率是 (1 - 0.5) * 0.3 = 15%
            # 比如 2分的废话，被忘概率是 (1 - 0.2) * 0.3 = 24%
            forget_prob = (1.0 - emo_weight) * 0.3
            
            # 抛骰子，如果命中概率，就把这条记忆的 ID 记下来准备删掉
            if random.random() < forget_prob:
                ids_to_delete.append(mem_id)
                print(f"🗑️ 遗忘机制触发: 慢慢淡忘了这件小事 [imp={importance}] {content[:30]}...")

        # 4. 执行淘汰：一次性把所有被判决的记忆从大脑（数据库）里抹除
        if ids_to_delete:
            await conn.execute(
                "DELETE FROM memories WHERE id = ANY($1::int[])",
                ids_to_delete
            )
            forgotten_count = len(ids_to_delete)
            print(f"✅ 遗忘机制执行完成, 共清理 {forgotten_count} 条边缘记忆")
            
    return forgotten_count
